from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from maru.projects.models import Project
from maru.projects.review import can_manage_accounts, can_review_applications
from maru.social.forms import SocialPostForm
from maru.social.models import SocialPost, SocialPublication


@login_required
def social_post_list_view(request, slug: str | None = None):
    project = _project_from_slug(slug)
    published_posts = SocialPost.objects.filter(
        project=project,
        status=SocialPost.PUBLISHED,
    )
    scheduled_posts = SocialPost.objects.filter(
        project=project,
        status=SocialPost.SCHEDULED,
    )
    if not can_review_applications(request.user):
        scheduled_posts = scheduled_posts.filter(author=request.user)
    own_drafts = SocialPost.objects.filter(
        author=request.user,
        project=project,
        status=SocialPost.DRAFT,
    )
    return render(
        request,
        "social/post_list.html",
        {
            "can_create_post": _can_create_post(request.user, project),
            "own_drafts": own_drafts,
            "project": project,
            "published_posts": published_posts,
            "scheduled_posts": scheduled_posts,
        },
    )


@login_required
def social_post_detail_view(request, pk: int, slug: str | None = None):
    project = _project_from_slug(slug)
    post = get_object_or_404(SocialPost, pk=pk)
    if post.project_id != (project.pk if project else None):
        raise Http404
    if not _can_view_post(request.user, post):
        raise Http404
    return render(
        request,
        "social/post_detail.html",
        {
            "can_edit_post": _can_edit_post(request.user, post),
            "post": post,
            "project": project,
        },
    )


@login_required
def create_social_post_view(request, slug: str | None = None):
    project = _project_from_slug(slug)
    if not _can_create_post(request.user, project):
        raise Http404
    form = SocialPostForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.project = project
        post.save()
        action = request.POST.get("action")
        if action == "publish":
            return _publish_or_schedule(request, post)
        post.save_version(created_by=request.user, action="save")
        messages.success(request, "Social media draft saved.")
        return redirect(
            _social_detail_route(project),
            pk=post.pk,
            **_slug_kwarg(project),
        )
    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "heading": "New Social Media Post",
            "post": None,
            "project": project,
        },
    )


@login_required
def edit_social_post_view(request, pk: int, slug: str | None = None):
    project = _project_from_slug(slug)
    post = get_object_or_404(SocialPost, pk=pk)
    if post.project_id != (project.pk if project else None):
        raise Http404
    if not _can_edit_post(request.user, post):
        raise Http404
    form = SocialPostForm(request.POST or None, request.FILES or None, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save()
        action = request.POST.get("action")
        if action == "publish":
            return _publish_or_schedule(request, post)
        post.save_version(created_by=request.user, action="save")
        messages.success(request, "Social media draft saved.")
        return redirect(
            _social_detail_route(project),
            pk=post.pk,
            **_slug_kwarg(project),
        )
    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "heading": f"Edit {post.title}",
            "post": post,
            "project": project,
        },
    )


def _project_from_slug(slug: str | None):
    if not slug:
        return None
    return get_object_or_404(Project, slug=slug)


def _social_detail_route(project) -> str:
    return "social:project_detail" if project else "social:detail"


def _slug_kwarg(project) -> dict:
    return {"slug": project.slug} if project else {}


def _can_view_post(user, post: SocialPost) -> bool:
    return post.is_published or _can_edit_post(user, post)


def _can_edit_post(user, post: SocialPost) -> bool:
    if post.project and post.project.is_closed and not can_manage_accounts(user):
        return False
    return post.author_id == user.id or can_review_applications(user)


def _can_create_post(user, project) -> bool:
    return not project or not project.is_closed or can_manage_accounts(user)


def publication_queue_summary(post: SocialPost) -> dict[str, int]:
    summary = {status: 0 for status, _label in SocialPublication.STATUS_CHOICES}
    for status in post.publications.values_list("status", flat=True):
        summary[status] += 1
    return summary


def _publish_or_schedule(request, post: SocialPost):
    detail_route = _social_detail_route(post.project)
    route_kwargs = {"pk": post.pk, **_slug_kwarg(post.project)}
    if post.scheduled_for and post.scheduled_for > timezone.now():
        post.schedule(scheduled_for=post.scheduled_for, created_by=request.user)
        messages.success(request, "Social media post scheduled for publication.")
        return redirect(detail_route, **route_kwargs)
    post.publish(created_by=request.user)
    messages.success(
        request,
        "Social media post published and queued for configured channels.",
    )
    return redirect(detail_route, **route_kwargs)
