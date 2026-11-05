from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ClientForm, JobFilterForm, JobForm, NoteForm
from .models import Change, Client, Note
from .services import clients_for, finance, initialize_job, jobs_for


@login_required
@permission_required("crm.view_job", raise_exception=True)
def dashboard(request):
    qs = jobs_for(request.user)
    active = qs.filter(archived_at__isnull=True).exclude(
        status__in=["closed", "delivered"]
    )
    form = JobFilterForm(request.GET)
    form.fields["client"].queryset = Client.objects.filter(job__in=qs).distinct()
    from django.contrib.auth import get_user_model

    form.fields["assigned_to"].queryset = get_user_model().objects.filter(
        pk__in=qs.values("assigned_to_id")
    )
    if not finance(request.user):
        form.fields["sort"].choices = [
            (k, v) for k, v in form.fields["sort"].choices if "agreed_price" not in k
        ]
    jobs = qs
    data = {}
    if form.is_valid():
        data = form.cleaned_data
        q = data.get("q")
        if q:
            jobs = jobs.filter(
                Q(number__icontains=q)
                | Q(title__icontains=q)
                | Q(address__icontains=q)
                | Q(client__name__icontains=q)
            )
        for key in ["status", "service", "client", "assigned_to"]:
            if data.get(key):
                jobs = jobs.filter(**{key: data[key]})
        if data.get("due_from"):
            jobs = jobs.filter(due_date__gte=data["due_from"])
        if data.get("due_to"):
            jobs = jobs.filter(due_date__lte=data["due_to"])
        if data.get("archive") == "only":
            jobs = jobs.filter(archived_at__isnull=False)
        elif data.get("archive") != "all":
            jobs = jobs.filter(archived_at__isnull=True)
        jobs = jobs.order_by(data.get("sort") or "due_date", "pk")
    else:
        jobs = jobs.none()
    links = {}
    for column in ["due_date", "status", "number", "client__name"]:
        query = request.GET.copy()
        query["sort"] = "-" + column if data.get("sort") == column else column
        links[column] = query.urlencode()
    return render(
        request,
        "crm/dashboard.html",
        {
            "jobs": jobs,
            "filters": form,
            "sort_links": links,
            "total": qs.count(),
            "active": active.count(),
            "overdue": active.filter(due_date__lt=timezone.localdate()).count(),
            "waiting": active.filter(status="waiting").count(),
            "notifications": request.user.crm_notifications.filter(
                read_at__isnull=True, job__in=qs
            )[:20],
        },
    )


@login_required
@permission_required("crm.view_client", raise_exception=True)
def clients(request):
    qs = clients_for(request.user)
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(company_id__icontains=query)
            | Q(phone__icontains=query)
        )
    from .sorting import ordered

    qs = ordered(
        qs, request, {"name", "email", "phone", "company_id", "billing_address"}, "name"
    )
    return render(
        request,
        "crm/clients.html",
        {"clients": qs.prefetch_related("contacts"), "query": query},
    )


@login_required
@permission_required("crm.add_client", raise_exception=True)
def client_new(request):
    form = ClientForm(
        request.POST or None, initial=request.session.pop("ares_client", {})
    )
    if request.method == "POST" and form.is_valid():
        client = form.save(commit=False)
        client.created_by = request.user
        client.save()
        return redirect("client_detail", pk=client.pk)
    return render(
        request, "crm/client_form.html", {"form": form, "title": "Nový klient"}
    )


@login_required
@permission_required("crm.add_job", raise_exception=True)
def job_new(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = JobForm(
        request.POST or None,
        initial={"assigned_to": request.user, "client": request.GET.get("client")},
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                job = form.save()
                initialize_job(job)
            return redirect("job_detail", pk=job.pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "crm/job_form.html", {"form": form, "title": "Nová zakázka"})


@login_required
@permission_required("crm.view_job", raise_exception=True)
def job_detail(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    form = NoteForm(request.POST or None)
    if job.archived_at and request.method == "POST":
        raise PermissionDenied("Archiv je pouze ke čtení.")
    if request.method == "POST":
        if not request.user.has_perm("crm.add_note"):
            raise PermissionDenied
        if form.is_valid():
            Note.objects.create(
                job=job, author=request.user, text=form.cleaned_data["text"]
            )
            return redirect("job_detail", pk=pk)
    docs = (
        job.documents.all()
        if request.user.is_superuser
        else job.documents.filter(
            Q(internal=False) | Q(allowed_users=request.user)
        ).distinct()
    )
    history = []
    if request.user.has_perm("crm.view_change"):
        for change in job.changes.select_related("author"):
            hidden = [] if finance(request.user) else ["agreed_price", "billing_text"]
            history.append(
                {
                    "author": change.author,
                    "created_at": change.created_at,
                    "before": {
                        k: v for k, v in change.before.items() if k not in hidden
                    },
                    "after": {k: v for k, v in change.after.items() if k not in hidden},
                }
            )
    return render(
        request,
        "crm/detail.html",
        {
            "job": job,
            "form": form,
            "documents": docs,
            "job_mail": __import__(
                "crm.models", fromlist=["ReceivedMail"]
            ).ReceivedMail.objects.filter(Q(job=job) | Q(inquiry__job=job))
            if request.user.is_superuser
            else [],
            "job_messages": __import__(
                "crm.models", fromlist=["Message"]
            ).Message.objects.filter(Q(job=job) | Q(inquiry__job=job))
            if request.user.is_superuser
            else [],
            "history": history,
            "can_finance": finance(request.user),
        },
    )


@login_required
@permission_required("crm.change_job", raise_exception=True)
def job_edit(request, pk):
    job = get_object_or_404(jobs_for(request.user), pk=pk)
    if job.archived_at:
        raise PermissionDenied("Archiv je pouze ke čtení.")
    before = {k: str(v) for k, v in model_to_dict(job).items()}
    form = JobForm(request.POST or None, instance=job)
    if not request.user.is_superuser:
        for field in [
            "client",
            "assigned_to",
            "property",
            "contact",
            "new_client_name",
            "new_client_email",
            "new_client_phone",
            "new_client_address",
        ]:
            form.fields.pop(field, None)
    if not finance(request.user):
        form.fields.pop("agreed_price", None)
        form.fields.pop("billing_text", None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            job = form.save()
            after = {k: str(v) for k, v in model_to_dict(job).items()}
            if before != after:
                Change.objects.create(
                    job=job, author=request.user, before=before, after=after
                )
        return redirect("job_detail", pk=pk)
    return render(
        request, "crm/job_form.html", {"form": form, "title": f"Upravit {job.number}"}
    )
