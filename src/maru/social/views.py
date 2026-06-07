from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from maru.projects.review import can_review_applications
from maru.social.forms import SocialPostForm
from maru.social.models import SocialPost, SocialPublication


@login_required
def social_post_list_view(request):
    published_posts = SocialPost.objects.filter(status=SocialPost.PUBLISHED)
    scheduled_posts = SocialPost.objects.filter(status=SocialPost.SCHEDULED)
    if not can_review_applications(request.user):
        scheduled_posts = scheduled_posts.filter(author=request.user)
    own_drafts = SocialPost.objects.filter(
        author=request.user,
        status=SocialPost.DRAFT,
    )
    return render(
        request,
        "social/post_list.html",
        {
            "own_drafts": own_drafts,
            "published_posts": published_posts,
            "scheduled_posts": scheduled_posts,
        },
    )


@login_required
def social_post_detail_view(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    if not _can_view_post(request.user, post):
        raise Http404
    return render(request, "social/post_detail.html", {"post": post})


@login_required
def create_social_post_view(request):
    form = SocialPostForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.save()
        action = request.POST.get("action")
        if action == "publish":
            return _publish_or_schedule(request, post)
        post.save_version(created_by=request.user, action="save")
        messages.success(request, "Social media draft saved.")
        return redirect("social:detail", pk=post.pk)
    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "heading": "New Social Media Post",
            "post": None,
        },
    )


@login_required
def edit_social_post_view(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
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
        return redirect("social:detail", pk=post.pk)
    return render(
        request,
        "social/post_form.html",
        {
            "form": form,
            "heading": f"Edit {post.title}",
            "post": post,
        },
    )


def _can_view_post(user, post: SocialPost) -> bool:
    return post.is_published or _can_edit_post(user, post)


def _can_edit_post(user, post: SocialPost) -> bool:
    return post.author_id == user.id or can_review_applications(user)


def publication_queue_summary(post: SocialPost) -> dict[str, int]:
    summary = {status: 0 for status, _label in SocialPublication.STATUS_CHOICES}
    for status in post.publications.values_list("status", flat=True):
        summary[status] += 1
    return summary


def _publish_or_schedule(request, post: SocialPost):
    if post.scheduled_for and post.scheduled_for > timezone.now():
        post.schedule(scheduled_for=post.scheduled_for, created_by=request.user)
        messages.success(request, "Social media post scheduled for publication.")
        return redirect("social:detail", pk=post.pk)
    post.publish(created_by=request.user)
    messages.success(
        request,
        "Social media post published and queued for configured channels.",
    )
    return redirect("social:detail", pk=post.pk)
