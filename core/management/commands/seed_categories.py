"""Create a starter set of product categories.

Categories are the only data a new marketplace needs before sellers can add
listings. This command adds *categories only*: no fake users, products or
orders. It is safe to run more than once.

    python manage.py seed_categories
"""
from django.core.management.base import BaseCommand

from products.models import Category

DEFAULT_CATEGORIES = [
    "Electronics",
    "Fashion",
    "Home and Garden",
    "Beauty and Health",
    "Phones and Tablets",
    "Computers",
    "Groceries",
    "Books and Stationery",
    "Sports and Outdoors",
    "Baby and Kids",
    "Vehicles and Parts",
    "Services",
]


class Command(BaseCommand):
    help = "Create starter product categories (categories only, no sample products)."

    def handle(self, *args, **options):
        created = 0
        for name in DEFAULT_CATEGORIES:
            _category, was_created = Category.objects.get_or_create(name=name)
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(f"{created} categories created, {len(DEFAULT_CATEGORIES) - created} already existed.")
        )
