from .services import export_allowed, finance


def capabilities(request):
    user = request.user
    if not user.is_authenticated:
        return {"can_finance": False, "can_export": False}
    return {"can_finance": finance(user), "can_export": export_allowed(user)}
