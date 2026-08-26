---
layout: default
title: Home
---

{% assign all_posts = site.posts | concat: site.notes | sort: "date" | reverse %}

<header class="page-header">
  <div>
    <p class="page-kicker">DEV NOTES / INDEX</p>
    <h1>개발 기록</h1>
    <p class="page-subtitle">만들고, 부수고, 다시 이해한 것들을 기록합니다.</p>
  </div>
  <p class="page-total" id="visible-post-count">전체 글 {{ all_posts.size }}개</p>
</header>

<section class="post-list" id="post-list" aria-live="polite">
  {% for post in all_posts %}
    <article class="post-card">
      <a class="post-card__link" href="{{ post.url | relative_url }}">
        <div class="post-card__topline">
          <h2>{{ post.title }}</h2>
          <time datetime="{{ post.date | date: '%Y-%m-%d' }}">{{ post.date | date: "%Y.%m.%d" }}</time>
        </div>
        <p class="post-card__excerpt">{{ post.excerpt | strip_html | strip_newlines | truncate: 180 }}</p>
        {% if post.tags %}
          <div class="post-tags" aria-label="태그">
            {% for tag in post.tags %}<span>#{{ tag }}</span>{% endfor %}
          </div>
        {% endif %}
      </a>
    </article>
  {% endfor %}
</section>

<p class="post-empty{% if all_posts.size > 0 %} is-hidden{% endif %}" id="post-empty">
  아직 작성한 글이 없습니다. <code>_posts</code> 또는 <code>_notes</code>에 첫 번째 기록을 추가해보세요.
</p>
