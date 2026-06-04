from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import TemplateParty
from .services.template_party_service import create_system_party_fields


@receiver(post_save, sender=TemplateParty)
def create_required_party_fields(sender, instance, created, **kwargs):
    if created:
        create_system_party_fields(instance)