from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

class Client(models.Model):
    name = models.CharField('Jméno / firma', max_length=200)
    email = models.EmailField('E-mail', blank=True)
    phone = models.CharField('Telefon', max_length=40, blank=True)
    company_id = models.CharField('IČO', max_length=20, blank=True)
    billing_address = models.TextField('Fakturační adresa', blank=True)
    def __str__(self): return self.name

class Sequence(models.Model):
    year = models.PositiveIntegerField(unique=True)
    value = models.PositiveIntegerField(default=0)

class Job(models.Model):
    SERVICES = [('penb','PENB'), ('passport','Pasport'), ('both','PENB + pasport'), ('other','Jiná služba')]
    STATES = [('new','Příprava'),('waiting','Čeká na podklady'),('survey','Zaměření'),('working','Zpracování'),('review','Kontrola'),('ready','Připraveno k předání'),('delivered','Předáno'),('closed','Uzavřeno')]
    number = models.CharField('Číslo',max_length=24,unique=True,editable=False)
    title = models.CharField('Název zakázky',max_length=250)
    client = models.ForeignKey(Client,on_delete=models.PROTECT,verbose_name='Klient')
    address = models.TextField('Adresa nemovitosti')
    service = models.CharField('Služba',max_length=20,choices=SERVICES,default='penb')
    status = models.CharField('Stav',max_length=20,choices=STATES,default='new')
    due_date = models.DateField('Termín vyhotovení')
    description = models.TextField('Popis zakázky',blank=True)
    next_step = models.CharField('Další krok',max_length=250,blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,verbose_name='Odpovědná osoba')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['due_date','id']
    @property
    def overdue(self): return self.due_date < timezone.localdate() and self.status not in ('delivered','closed')
    def save(self,*args,**kwargs):
        if self.number: return super().save(*args,**kwargs)
        # Pilot numbering starts in 2027; later years have their own series.
        year=max(2027,timezone.localdate().year)
        with transaction.atomic():
            seq,_=Sequence.objects.get_or_create(year=year)
            Sequence.objects.filter(pk=seq.pk).update(value=F('value')+1)
            seq.refresh_from_db()
            self.number=f'Z{year % 100:02d}/{seq.value:03d}'
            super().save(*args,**kwargs)
    def __str__(self): return f'{self.number} — {self.title}'

class Note(models.Model):
    job = models.ForeignKey(Job,on_delete=models.CASCADE,related_name='notes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at','-id']

class Change(models.Model):
    job = models.ForeignKey(Job,on_delete=models.CASCADE,related_name='changes')
    author = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    before = models.JSONField()
    after = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at','-id']
