from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ClientForm, JobForm, NoteForm
from .models import Change, Client, Job, Note
from .services import finance, initialize_job, jobs_for


@login_required
@permission_required("crm.view_job", raise_exception=True)
def dashboard(request):
    qs = jobs_for(request.user)
    active = qs.exclude(status__in=["closed", "delivered"])
    query = request.GET.get("q", "").strip()
    jobs = qs
    if query:
        jobs = jobs.filter(
            Q(number__icontains=query)
            | Q(title__icontains=query)
            | Q(address__icontains=query)
            | Q(client__name__icontains=query)
        )
    state = request.GET.get("status", "")
    if state:
        jobs = jobs.filter(status=state)
    return render(
        request,
        "crm/dashboard.html",
        {
            "jobs": jobs,
            "query": query,
            "states": Job.STATES,
            "selected": state,
            "total": qs.count(),
            "active": active.count(),
            "overdue": active.filter(due_date__lt=timezone.localdate()).count(),
            "waiting": active.filter(status="waiting").count(),
            "notifications": request.user.crm_notifications.filter(
                read_at__isnull=True, job__in=jobs_for(request.user)
            )[:20],
        },
    )


@login_required
@permission_required("crm.view_client", raise_exception=True)
def clients(request):
    qs = (
        Client.objects.all()
        if request.user.is_superuser
        else Client.objects.filter(job__in=jobs_for(request.user)).distinct()
    )
    return render(
        request, "crm/clients.html", {"clients": qs.prefetch_related("contacts")}
    )


@login_required
@permission_required("crm.add_client", raise_exception=True)
def client_new(request):
    form = ClientForm(
        request.POST or None, initial=request.session.pop("ares_client", {})
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("clients")
    return render(request, "crm/form.html", {"form": form, "title": "Nový klient"})


@login_required
@permission_required("crm.add_job", raise_exception=True)
def job_new(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    form = JobForm(request.POST or None, initial={"assigned_to": request.user})
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                job = form.save()
                initialize_job(job)
            return redirect("job_detail", pk=job.pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, "crm/form.html", {"form": form, "title": "Nová zakázka"})


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
            hidden = [] if finance(request.user) else ["agreed_price"]
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
        for field in ["client", "assigned_to", "property", "contact"]:
            form.fields.pop(field)
    if not finance(request.user):
        form.fields.pop("agreed_price", None)
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
        request, "crm/form.html", {"form": form, "title": f"Upravit {job.number}"}
    )
