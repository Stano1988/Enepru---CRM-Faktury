from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .models import Client, Job, Note, Change
from .forms import ClientForm, JobForm, NoteForm

def jobs_for(user):
    qs=Job.objects.select_related('client','assigned_to')
    return qs if user.is_superuser else qs.filter(assigned_to=user)

@login_required
@permission_required('crm.view_job',raise_exception=True)
def dashboard(request):
    qs=jobs_for(request.user)
    active=qs.exclude(status__in=['closed','delivered'])
    query=request.GET.get('q','').strip()
    jobs=qs
    if query: jobs=jobs.filter(Q(number__icontains=query)|Q(title__icontains=query)|Q(address__icontains=query)|Q(client__name__icontains=query))
    state=request.GET.get('status','')
    if state: jobs=jobs.filter(status=state)
    return render(request,'crm/dashboard.html',{'jobs':jobs,'query':query,'states':Job.STATES,'selected':state,'total':qs.count(),'active':active.count(),'overdue':active.filter(due_date__lt=timezone.localdate()).count(),'waiting':active.filter(status='waiting').count()})

@login_required
@permission_required('crm.view_client',raise_exception=True)
def clients(request):
    qs=Client.objects.all() if request.user.is_superuser else Client.objects.filter(job__assigned_to=request.user).distinct()
    return render(request,'crm/clients.html',{'clients':qs})

@login_required
@permission_required('crm.add_client',raise_exception=True)
def client_new(request):
    form=ClientForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        form.save(); return redirect('clients')
    return render(request,'crm/form.html',{'form':form,'title':'Nový klient'})

@login_required
@permission_required('crm.add_job',raise_exception=True)
def job_new(request):
    if not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    form=JobForm(request.POST or None,initial={'assigned_to':request.user})
    if request.method=='POST' and form.is_valid():
        job=form.save();return redirect('job_detail',pk=job.pk)
    return render(request,'crm/form.html',{'form':form,'title':'Nová zakázka'})

@login_required
@permission_required('crm.view_job',raise_exception=True)
def job_detail(request,pk):
    job=get_object_or_404(jobs_for(request.user),pk=pk)
    form=NoteForm(request.POST or None)
    if request.method=='POST':
        if not request.user.has_perm('crm.add_note'):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if form.is_valid():
            Note.objects.create(job=job,author=request.user,text=form.cleaned_data['text'])
            return redirect('job_detail',pk=pk)
    return render(request,'crm/detail.html',{'job':job,'form':form})

@login_required
@permission_required('crm.change_job',raise_exception=True)
def job_edit(request,pk):
    job=get_object_or_404(jobs_for(request.user),pk=pk)
    before={k:str(v) for k,v in model_to_dict(job).items()}
    form=JobForm(request.POST or None,instance=job)
    if not request.user.is_superuser:
        for field in ['client','assigned_to']: form.fields.pop(field)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            job=form.save()
            after={k:str(v) for k,v in model_to_dict(job).items()}
            if before!=after: Change.objects.create(job=job,author=request.user,before=before,after=after)
        return redirect('job_detail',pk=pk)
    return render(request,'crm/form.html',{'form':form,'title':f'Upravit {job.number}'})
