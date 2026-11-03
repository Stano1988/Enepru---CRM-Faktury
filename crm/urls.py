from django.urls import path
from . import views
urlpatterns=[path('',views.dashboard,name='dashboard'),path('clients/',views.clients,name='clients'),path('clients/new/',views.client_new,name='client_new'),path('jobs/new/',views.job_new,name='job_new'),path('jobs/<int:pk>/',views.job_detail,name='job_detail'),path('jobs/<int:pk>/edit/',views.job_edit,name='job_edit')]
