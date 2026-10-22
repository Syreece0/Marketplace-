from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserProfile


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    """Every user gets a UserProfile, including accounts made by createsuperuser."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
