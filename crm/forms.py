from django import forms
from .models import Client, Job
class ClientForm(forms.ModelForm):
    class Meta:
        model=Client
        fields=['name','email','phone','company_id','billing_address']
class JobForm(forms.ModelForm):
    class Meta:
        model=Job
        fields=['title','client','address','service','status','due_date','assigned_to','next_step','description']
        widgets={'due_date':forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d')}
class NoteForm(forms.Form):
    text=forms.CharField(label='Nová interní poznámka',widget=forms.Textarea(attrs={'rows':3}),max_length=10000)
