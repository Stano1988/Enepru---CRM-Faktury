"""Read-only previews and atomic, permission checked document bundles."""

import io
import zipfile
from pathlib import Path

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .services import documents_for, event, export_allowed


def visible(user):
    return documents_for(user).filter(deleted_at__isnull=True)


@login_required
@permission_required("crm.view_document", raise_exception=True)
def preview(request, pk):
    doc = get_object_or_404(visible(request.user), pk=pk)
    # documents_for also enforces per-document internal sharing rules.
    suffix = Path(doc.file.name).suffix.lower()
    types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    if suffix not in types:
        return HttpResponseBadRequest(
            "Tento typ nemá bezpečný náhled. Použijte stažení."
        )
    response = FileResponse(
        doc.file.open("rb"),
        as_attachment=False,
        filename=Path(doc.name).name,
        content_type=types[suffix],
    )
    # Isolate active PDF content; the file never receives app scripting rights.
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    event(request.user, "Otevřen náhled dokumentu", doc.job, document=doc.pk)
    return response


@login_required
@permission_required("crm.view_document", raise_exception=True)
@require_POST
def bundle(request):
    if not export_allowed(request.user):
        raise PermissionDenied
    try:
        ids = {int(pk) for pk in request.POST.getlist("documents")}
    except ValueError:
        return HttpResponseBadRequest("Neplatný výběr.")
    if not ids or len(ids) > 100:
        return HttpResponseBadRequest("Vyberte 1 až 100 souborů.")
    docs = list(visible(request.user).filter(pk__in=ids).select_related("job"))
    if len(docs) != len(ids):
        raise PermissionDenied
    if sum(doc.file.size for doc in docs) > 100 * 1024 * 1024:
        return HttpResponseBadRequest(
            "Výběr překračuje 100 MB. Stáhněte menší skupiny."
        )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc in docs:
            name = Path(doc.name.replace("\\", "/")).name or "soubor"
            with doc.file.open("rb") as handle:
                archive.writestr(f"{doc.pk}-{name}", handle.read())
    event(request.user, "Stažena skupina dokumentů", documents=sorted(ids))
    response = HttpResponse(out.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="Dokumenty.zip"'
    return response
