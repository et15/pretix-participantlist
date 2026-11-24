from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from pretix.control.permissions import OrganizerPermissionRequiredMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin
from pretix.helpers.compat import CompatDeleteView

from . import logs
from .fields import STATIC_FIELD_CHOICES, organizer_question_details
from .forms import BrandingForm, ListConfigurationForm
from .models import ListConfiguration, OrganizerBranding

PERMISSION = "organizer.settings.general:write"


def _kinds_url(organizer):
    return reverse(
        "plugins:pretix_participantlist:kinds", kwargs={"organizer": organizer.slug}
    )


class BrandingUpdateView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, UpdateView
):
    model = OrganizerBranding
    form_class = BrandingForm
    template_name = "pretix_participantlist/branding_form.html"
    permission = PERMISSION
    context_object_name = "branding"

    def get_object(self, queryset=None):
        obj, _created = OrganizerBranding.objects.get_or_create(
            organizer=self.request.organizer
        )
        return obj

    def get_success_url(self):
        return reverse(
            "plugins:pretix_participantlist:branding",
            kwargs={"organizer": self.request.organizer.slug},
        )

    @transaction.atomic
    def form_valid(self, form):
        fields = BrandingForm.Meta.fields
        before = logs.snapshot(
            OrganizerBranding.objects.get(pk=form.instance.pk), fields
        )
        messages.success(self.request, _("Your changes have been saved."))
        response = super().form_valid(form)
        changed = logs.changes(before, logs.snapshot(self.object, fields))
        if changed:
            self.object.log_action(
                logs.BRANDING_CHANGED, user=self.request.user, data=changed
            )
        return response


class ListConfigurationListView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, ListView
):
    model = ListConfiguration
    template_name = "pretix_participantlist/kind_list.html"
    permission = PERMISSION
    context_object_name = "kinds"

    def get_queryset(self):
        return self.request.organizer.participantlist_configs.all()


class ListConfigurationPlaceholdersView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, ListView
):
    template_name = "pretix_participantlist/kind_placeholders.html"
    permission = PERMISSION
    context_object_name = "placeholders"

    def get_queryset(self):
        return organizer_question_details(self.request.organizer)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["static_fields"] = STATIC_FIELD_CHOICES
        return ctx


class ListConfigurationCreateView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, CreateView
):
    model = ListConfiguration
    form_class = ListConfigurationForm
    template_name = "pretix_participantlist/kind_form.html"
    permission = PERMISSION

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organizer"] = self.request.organizer
        return kwargs

    def get_success_url(self):
        return _kinds_url(self.request.organizer)

    @transaction.atomic
    def form_valid(self, form):
        form.instance.organizer = self.request.organizer
        if not self.request.organizer.participantlist_configs.filter(
            is_default=True
        ).exists():
            form.instance.is_default = True
        messages.success(self.request, _("The list kind has been created."))
        response = super().form_valid(form)
        self.object.log_action(
            logs.KIND_ADDED,
            user=self.request.user,
            data=logs.snapshot(self.object, logs.KIND_LOG_FIELDS),
        )
        return response


class ListConfigurationUpdateView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, UpdateView
):
    model = ListConfiguration
    form_class = ListConfigurationForm
    template_name = "pretix_participantlist/kind_form.html"
    permission = PERMISSION
    pk_url_kwarg = "kind"

    def get_object(self, queryset=None):
        return get_object_or_404(
            ListConfiguration,
            organizer=self.request.organizer,
            pk=self.kwargs.get("kind"),
        )

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["organizer"] = self.request.organizer
        return kwargs

    def get_success_url(self):
        return _kinds_url(self.request.organizer)

    @transaction.atomic
    def form_valid(self, form):
        before = logs.snapshot(
            ListConfiguration.objects.get(pk=form.instance.pk), logs.KIND_LOG_FIELDS
        )
        messages.success(self.request, _("The list kind has been updated."))
        response = super().form_valid(form)
        changed = logs.changes(before, logs.snapshot(self.object, logs.KIND_LOG_FIELDS))
        if changed:
            self.object.log_action(
                logs.KIND_CHANGED, user=self.request.user, data=changed
            )
        return response


class ListConfigurationDeleteView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, CompatDeleteView
):
    model = ListConfiguration
    template_name = "pretix_participantlist/kind_delete.html"
    permission = PERMISSION
    context_object_name = "kind"
    pk_url_kwarg = "kind"

    def get_object(self, queryset=None):
        return get_object_or_404(
            ListConfiguration,
            organizer=self.request.organizer,
            pk=self.kwargs.get("kind"),
        )

    def get_success_url(self):
        return _kinds_url(self.request.organizer)

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        was_default = self.object.is_default
        deleted = {"id": self.object.pk, "name": self.object.name}
        self.object.log_action(logs.KIND_DELETED, user=request.user, data=deleted)
        self.object.delete()
        if was_default:
            other = self.request.organizer.participantlist_configs.first()
            if other:
                other.is_default = True
                other.save(update_fields=["is_default"])
                other.log_action(
                    logs.KIND_DEFAULT,
                    user=request.user,
                    data={"automatic": True, "previous": deleted},
                )
        messages.success(request, _("The list kind has been deleted."))
        return redirect(self.get_success_url())


class ListConfigurationSetDefaultView(
    OrganizerDetailViewMixin, OrganizerPermissionRequiredMixin, DetailView
):
    model = ListConfiguration
    permission = PERMISSION
    pk_url_kwarg = "kind"

    def get_object(self, queryset=None):
        return get_object_or_404(
            ListConfiguration,
            organizer=self.request.organizer,
            pk=self.kwargs.get("kind"),
        )

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        others = self.request.organizer.participantlist_configs.exclude(pk=obj.pk)
        previous = others.filter(is_default=True).first()
        others.update(is_default=False)
        if not obj.is_default:
            obj.is_default = True
            obj.save(update_fields=["is_default"])
            obj.log_action(
                logs.KIND_DEFAULT,
                user=request.user,
                data={
                    "automatic": False,
                    "previous": {"id": previous.pk, "name": previous.name}
                    if previous
                    else None,
                },
            )
        messages.success(request, _("The default list kind has been changed."))
        return redirect(_kinds_url(self.request.organizer))
