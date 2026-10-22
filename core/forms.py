"""Shared form helpers."""
from django import forms
from django.core.mail import send_mail
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class BootstrapFormMixin:
    """Adds Bootstrap CSS classes to widgets and marks invalid fields.

    Invalid fields also get ``aria-invalid`` so errors are not conveyed by
    colour alone (the template shows an icon and text message as well).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            elif isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                css = ""
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {css}".strip()

    def full_clean(self):
        super().full_clean()
        if self.is_bound and self._errors:
            for name in self._errors:
                if name in self.fields:
                    widget = self.fields[name].widget
                    widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()
                    widget.attrs["aria-invalid"] = "true"


class ContactForm(BootstrapFormMixin, forms.Form):
    name = forms.CharField(label=_("Your name"), max_length=100)
    email = forms.EmailField(label=_("Email address"))
    subject = forms.CharField(label=_("Subject"), max_length=150)
    message = forms.CharField(
        label=_("Message"), widget=forms.Textarea(attrs={"rows": 5}), max_length=3000
    )

    def clean_subject(self):
        # Newlines in an email subject are a header-injection technique.
        subject = self.cleaned_data["subject"].strip()
        if "\n" in subject or "\r" in subject:
            raise forms.ValidationError(_("The subject must be a single line."))
        return subject

    def send(self):
        data = self.cleaned_data
        body = f"From: {data['name']} <{data['email']}>\n\n{data['message']}"
        send_mail(
            subject=f"[{settings.SITE_NAME} contact] {data['subject']}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.CONTACT_EMAIL],
        )
