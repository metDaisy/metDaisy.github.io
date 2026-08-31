(function () {
  "use strict";

  const searchForm = document.querySelector("#post-search");
  const search = document.querySelector("#post-search-input");
  const clearButton = document.querySelector("#search-clear");
  const postList = document.querySelector("#post-list");
  const emptyState = document.querySelector("#post-empty");
  const count = document.querySelector("#visible-post-count");
  const tagButtons = Array.from(document.querySelectorAll(".tag-filter"));
  const searchIndex = document.body.dataset.searchIndex;
  const layout = document.querySelector(".site-layout");
  const sidebarToggle = document.querySelector("#sidebar-toggle");
  const sidebarStorageKey = "met-daisy-sidebar-collapsed";

  function setSidebarCollapsed(collapsed) {
    if (!layout || !sidebarToggle) return;
    layout.classList.toggle("is-sidebar-collapsed", collapsed);
    sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    sidebarToggle.setAttribute("aria-label", collapsed ? "사이드바 펼치기" : "사이드바 접기");
    sidebarToggle.title = collapsed ? "사이드바 펼치기" : "사이드바 접기";
    const icon = sidebarToggle.querySelector("[data-sidebar-icon]");
    if (icon) icon.textContent = collapsed ? "›" : "‹";
  }

  if (layout && sidebarToggle) {
    let collapsed = false;
    try {
      collapsed = window.localStorage.getItem(sidebarStorageKey) === "true";
    } catch (_error) {
      // Local storage can be unavailable in private or restricted contexts.
    }
    setSidebarCollapsed(collapsed);
    sidebarToggle.addEventListener("click", () => {
      const nextState = !layout.classList.contains("is-sidebar-collapsed");
      setSidebarCollapsed(nextState);
      try {
        window.localStorage.setItem(sidebarStorageKey, String(nextState));
      } catch (_error) {
        // The toggle still works for the current page.
      }
    });
  }

  if (!search || !searchIndex) return;

  let posts = [];
  let activeTag = "";

  const normalize = (value) => String(value || "").toLocaleLowerCase("ko-KR");

  function createPostCard(post) {
    const article = document.createElement("article");
    article.className = "post-card";

    const link = document.createElement("a");
    link.className = "post-card__link";
    link.href = post.url;

    const topline = document.createElement("div");
    topline.className = "post-card__topline";

    const title = document.createElement("h2");
    title.textContent = post.title;

    const date = document.createElement("time");
    date.textContent = post.date;

    const excerpt = document.createElement("p");
    excerpt.className = "post-card__excerpt";
    excerpt.textContent = post.excerpt;

    topline.append(title, date);
    link.append(topline, excerpt);

    if (post.tags.length) {
      const tags = document.createElement("div");
      tags.className = "post-tags";
      post.tags.forEach((tag) => {
        const tagElement = document.createElement("span");
        tagElement.textContent = `#${tag}`;
        tags.appendChild(tagElement);
      });
      link.appendChild(tags);
    }

    article.appendChild(link);
    return article;
  }

  function render() {
    const query = normalize(search.value.trim());
    const filteredPosts = posts.filter((post) => {
      const matchesTag = !activeTag || post.tags.includes(activeTag);
      const searchableText = normalize([
        post.title,
        post.excerpt,
        post.content,
        post.date,
        post.date_iso,
        post.tags.join(" ")
      ].join(" "));
      return matchesTag && (!query || searchableText.includes(query));
    });

    if (postList && emptyState) {
      postList.replaceChildren(...filteredPosts.map(createPostCard));
      emptyState.classList.toggle("is-hidden", filteredPosts.length > 0);
      emptyState.textContent = filteredPosts.length
        ? ""
        : query || activeTag
          ? "검색 조건에 맞는 글이 없습니다."
          : "아직 작성한 글이 없습니다. _posts 또는 _notes에 첫 번째 기록을 추가해보세요.";
    }

    if (count) {
      count.textContent = query || activeTag
        ? `${filteredPosts.length}개 검색됨`
        : `전체 글 ${posts.length}개`;
    }
    clearButton.hidden = !search.value;
  }

  function setActiveTag(tag) {
    activeTag = tag;
    tagButtons.forEach((button) => {
      const isActive = button.dataset.tag === tag;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
    render();
  }

  if (searchForm) {
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!postList) {
        const homeUrl = new URL(document.querySelector(".site-brand__link").href, window.location.href);
        if (search.value.trim()) homeUrl.searchParams.set("q", search.value.trim());
        window.location.href = homeUrl.toString();
        return;
      }
      render();
    });
  }
  search.addEventListener("input", render);
  clearButton.addEventListener("click", () => {
    search.value = "";
    search.focus();
    render();
  });
  tagButtons.forEach((button) => {
    button.addEventListener("click", () => setActiveTag(button.dataset.tag));
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      search.focus();
    }
    if (event.key === "Escape" && search.value) {
      search.value = "";
      render();
    }
  });

  const initialQuery = new URLSearchParams(window.location.search).get("q");
  if (initialQuery) search.value = initialQuery;

  fetch(searchIndex)
    .then((response) => {
      if (!response.ok) throw new Error(`Search index failed: ${response.status}`);
      return response.json();
    })
    .then((data) => {
      posts = data.map((post) => ({
        ...post,
        tags: Array.isArray(post.tags) ? post.tags : []
      }));
      render();
    })
    .catch(() => {
      document.querySelector("#search-hint").textContent = "검색 인덱스를 불러오지 못했습니다.";
    });
})();
