"""Only explicitly declared columns may reach ORDER BY."""


def ordered(qs, request, columns, default):
    key = request.GET.get("sort", default)
    if key.lstrip("-") not in columns:
        key = default
    return qs.order_by(key, "pk")
