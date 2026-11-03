from django.contrib import admin

from .models import Access, Automation


@admin.register(Access)
class AccessAdmin(admin.ModelAdmin):
    list_display = ["user", "all_jobs", "finances", "export"]
    autocomplete_fields = ["user"]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = [
        "enabled",
        "reminder_days",
        "second_days",
        "final_days",
        "auto_send",
    ]

    def has_add_permission(self, request):
        return request.user.is_superuser and not Automation.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.site_header = "Lahodný CRM — uživatelé a oprávnění"
