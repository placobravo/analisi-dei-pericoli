from decimal import Decimal
from pathlib import Path
from zipfile import BadZipFile

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from portal.models import Catalog, CatalogCategory, CatalogRow, CatalogVersion, Hazard

GENERAL_ROW_LABEL = "Tutte le materie prime appartenenti alla categoria"


def clean(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def key(kind, name):
    return kind, name.casefold()


def read_hazards(book):
    source = book["PERICOLI (G)"]
    matrix = book["PROBABILITA (P)"]
    rows = source.iter_rows(min_row=2, max_row=68, max_col=4, values_only=True)
    entries = {}
    for index, (_, kind, name, severity) in enumerate(rows, start=2):
        name = clean(name)
        kind = clean(kind)
        entry_key = key(kind, name)
        if not name or kind not in Hazard.Kind.values or entry_key in entries:
            raise CommandError(f"Pericolo non valido o duplicato alla riga {index} di PERICOLI (G).")
        # In questa versione del foglio un refuso in D10 è verificabile nella matrice.
        if index == 10 and severity == "ù":
            severity = matrix["M3"].value
            if clean(matrix["M1"].value) != name or clean(matrix["M2"].value) != kind or severity != 3:
                raise CommandError("La gravità in D10 non è verificabile nella matrice.")
        if type(severity) not in (int, float) or severity < 0:
            raise CommandError(f"Gravità non valida alla riga {index} di PERICOLI (G).")
        entries[entry_key] = (name, kind, Decimal(str(severity)))

    headers = matrix.iter_rows(min_row=1, max_row=3, min_col=5, max_col=71, values_only=True)
    ordered = []
    for position, (name, kind, severity) in enumerate(zip(*headers), start=1):
        match = entries.pop(key(clean(kind), clean(name)), None)
        if not match or type(severity) not in (int, float) or match[2] != Decimal(str(severity)):
            raise CommandError(f"Discordanza nel pericolo numero {position} della matrice.")
        ordered.append((*match, position))
    if len(ordered) != 67 or entries:
        raise CommandError("Il catalogo iniziale deve contenere i 67 pericoli della matrice.")
    return ordered


def read_rows(book):
    source = book["PROBABILITA (P)"]
    rows = []
    seen = set()
    for position, fields in enumerate(source.iter_rows(min_row=4, max_row=26, max_col=3, values_only=True), start=1):
        use, category, label = map(clean, fields)
        if not category or not label:
            raise CommandError(f"Voce non valida alla riga {position + 3} della matrice.")
        if label == GENERAL_ROW_LABEL:
            label = ""
        row_key = (category.casefold(), label.casefold())
        if row_key in seen:
            raise CommandError(f"Voce duplicata alla riga {position + 3} della matrice.")
        seen.add(row_key)
        rows.append((category, label, use, position))
    if len(rows) != 23:
        raise CommandError("Il catalogo iniziale deve contenere le 23 voci della matrice.")
    return rows


class Command(BaseCommand):
    help = "Importa e pubblica il catalogo iniziale dal foglio Excel corretto."

    def add_arguments(self, parser):
        parser.add_argument("workbook", type=Path)

    def handle(self, *args, workbook, **options):
        try:
            book = load_workbook(workbook, read_only=True, data_only=True)
            try:
                rows = read_rows(book)
                hazards = read_hazards(book)
            finally:
                book.close()
        except (OSError, BadZipFile, KeyError) as error:
            raise CommandError(f"Impossibile leggere il foglio Excel: {error}") from error

        with transaction.atomic():
            catalog = Catalog.objects.select_for_update().get(pk=1)
            if catalog.current_id or catalog.draft_id:
                raise CommandError("Esiste già un catalogo. L'importazione iniziale non lo sostituisce.")
            version = CatalogVersion.objects.create(number=1, published_at=timezone.now())
            categories = {}
            for name, label, use, position in rows:
                category_key = name.casefold()
                if category_key not in categories:
                    categories[category_key] = CatalogCategory.objects.create(version=version, name=name)
                CatalogRow.objects.create(
                    category=categories[category_key], label=label, intended_use=use, position=position
                )
            Hazard.objects.bulk_create([
                Hazard(version=version, name=name, kind=kind, severity=severity, position=position)
                for name, kind, severity, position in hazards
            ])
            catalog.current = version
            catalog.save(update_fields=["current"])
        self.stdout.write(self.style.SUCCESS(f"Catalogo v1 pubblicato con {len(rows)} voci e {len(hazards)} pericoli."))
