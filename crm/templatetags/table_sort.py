from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_column(context, field, label):
    request = context["request"]
    current = request.GET.get("sort", "")
    query = request.GET.copy()
    query["sort"] = "-" + field if current == field else field
    symbol = "↑" if current == field else "↓" if current == "-" + field else "↕"
    return format_html(
        '<a href="?{}" aria-label="Seřadit podle: {}">{} <span aria-hidden="true">{}</span></a>',
        query.urlencode(),
        label,
        label,
        symbol,
    )
