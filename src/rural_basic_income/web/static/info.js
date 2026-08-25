(function () {
  const state = {
    posts: [],
    selectedId: null,
    mode: "read",
  };

  const els = {
    root: document.getElementById("info-view"),
    readPanels: document.querySelectorAll("#info-view .info-read-panel"),
    formSection: document.querySelector("#info-view .info-form-section"),
    newButton: document.getElementById("info-new-button"),
    cancelButton: document.getElementById("info-cancel-button"),
    refresh: document.getElementById("info-refresh"),
    status: document.getElementById("info-status"),
    list: document.getElementById("info-post-list"),
    form: document.getElementById("info-form"),
    titleInput: document.getElementById("info-title-input"),
    bodyInput: document.getElementById("info-body-input"),
    createButton: document.getElementById("info-create-button"),
    detailTitle: document.getElementById("info-detail-title"),
    detailMeta: document.getElementById("info-detail-meta"),
    detailBody: document.getElementById("info-detail-body"),
  };

  async function infoJson(url, options = {}) {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      if (response.status === 404 && url.startsWith("/api/info")) {
        throw new Error("정보 API를 찾지 못했습니다. 웹 서버를 재시작하세요.");
      }
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.message) {
        throw new Error(detail.message);
      }
      throw new Error(typeof detail === "string" ? detail : "요청 실패");
    }
    return payload;
  }

  function formatDate(value) {
    if (!value) {
      return "";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return new Intl.DateTimeFormat("ko-KR", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  }

  function setStatus(message, isError = false) {
    if (!els.status) {
      return;
    }
    els.status.textContent = message;
    els.status.classList.toggle("error", isError);
  }

  function setMode(mode) {
    state.mode = mode;
    els.root.classList.toggle("is-editing", mode === "edit");
    els.formSection.classList.toggle("is-hidden", mode !== "edit");
    for (const panel of els.readPanels) {
      panel.classList.toggle("is-hidden", mode === "edit");
    }
    if (mode === "edit") {
      setStatus("새 글을 작성하세요");
      window.requestAnimationFrame(() => els.titleInput.focus());
      return;
    }
    setStatus(`${state.posts.length}개 글`);
    window.requestAnimationFrame(() => els.root.scrollIntoView({ block: "start" }));
  }

  function emptyDetail(message = "아직 선택된 글이 없습니다.") {
    state.selectedId = null;
    els.detailTitle.textContent = "글 없음";
    els.detailMeta.textContent = "";
    els.detailBody.innerHTML = `<p>${message}</p>`;
  }

  function renderList() {
    els.list.innerHTML = "";
    if (!state.posts.length) {
      els.list.innerHTML = '<div class="empty-list">저장된 정보 글이 없습니다.</div>';
      if (state.selectedId === null) {
        emptyDetail("새 글을 작성하면 여기에 본문이 표시됩니다.");
      }
      return;
    }

    for (const post of state.posts) {
      const button = document.createElement("button");
      button.className = "info-post-item";
      button.type = "button";
      button.dataset.infoId = post.id;
      button.classList.toggle("is-active", post.id === state.selectedId);
      button.innerHTML = `
        <strong></strong>
        <span></span>
      `;
      button.querySelector("strong").textContent = post.title;
      button.querySelector("span").textContent = formatDate(post.created_at);
      button.addEventListener("click", () => loadPost(post.id));
      els.list.appendChild(button);
    }
  }

  function renderDetail(post) {
    state.selectedId = post.id;
    els.detailTitle.textContent = post.title;
    els.detailMeta.textContent = formatDate(post.created_at);
    els.detailBody.innerHTML = post.body_html || "<p>본문 없음</p>";
    renderList();
  }

  async function loadPosts({ force = false } = {}) {
    if (!force && state.posts.length) {
      return;
    }
    setStatus("정보 글을 불러오는 중");
    try {
      const payload = await infoJson("/api/info");
      state.posts = payload.posts || [];
      renderList();
      setStatus(`${state.posts.length}개 글`);
      if (state.posts.length && state.selectedId === null) {
        await loadPost(state.posts[0].id);
      }
    } catch (error) {
      console.error(error);
      setStatus(error.message, true);
      emptyDetail("정보 글을 불러오지 못했습니다.");
    }
  }

  async function loadPost(infoId) {
    setStatus("본문을 불러오는 중");
    try {
      const payload = await infoJson(`/api/info/${encodeURIComponent(infoId)}`);
      renderDetail(payload.post);
      setStatus(`${state.posts.length}개 글`);
    } catch (error) {
      console.error(error);
      setStatus(error.message, true);
    }
  }

  async function createPost(event) {
    event.preventDefault();
    const title = els.titleInput.value.trim();
    const bodyMarkdown = els.bodyInput.value.trim();
    if (!title || !bodyMarkdown) {
      setStatus("제목과 본문을 입력하세요", true);
      return;
    }

    els.createButton.disabled = true;
    setStatus("저장하는 중");
    try {
      const payload = await infoJson("/api/info", {
        method: "POST",
        body: JSON.stringify({
          title,
          body_markdown: bodyMarkdown,
        }),
      });
      els.form.reset();
      state.posts = [
        {
          id: payload.post.id,
          title: payload.post.title,
          created_at: payload.post.created_at,
        },
        ...state.posts.filter((post) => post.id !== payload.post.id),
      ];
      setMode("read");
      renderDetail(payload.post);
      setStatus("저장했습니다");
    } catch (error) {
      console.error(error);
      setStatus(error.message, true);
    } finally {
      els.createButton.disabled = false;
    }
  }

  function bindEvents() {
    els.newButton.addEventListener("click", () => {
      els.form.reset();
      setMode("edit");
    });
    els.cancelButton.addEventListener("click", () => {
      els.form.reset();
      setMode("read");
    });
    els.refresh.addEventListener("click", () => {
      state.posts = [];
      loadPosts({ force: true });
    });
    els.form.addEventListener("submit", createPost);
    window.addEventListener("rbi:viewchange", (event) => {
      if (event.detail?.viewTarget === "info-view") {
        loadPosts();
      }
    });
  }

  function init() {
    if (!els.list) {
      return;
    }
    bindEvents();
    if (window.location.hash === "#info") {
      document.querySelector('[data-view-target="info-view"]')?.click();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
