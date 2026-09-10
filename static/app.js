const calendarRoot = document.getElementById("calendar-root");
const loadingNote = document.getElementById("loading-note");
const profileSummaryEl = document.getElementById("profile-summary");
const overallProgressEl = document.getElementById("overall-progress");
const lookupForm = document.getElementById("lookup-form");
const profileInput = document.getElementById("profile-input");
const checkBtn = document.getElementById("check-btn");
const demoBtn = document.getElementById("demo-btn");
const lookupError = document.getElementById("lookup-error");

let baseCalendar = null;

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function renderCalendar(data, { withStatus }) {
  calendarRoot.innerHTML = "";

  data.phases.forEach((phase) => {
    const section = document.createElement("section");
    section.className = "phase";

    const progressHtml = withStatus
      ? `<span class="phase-progress">${phase.progress.done} / ${phase.progress.total} modules &mdash; ${phase.progress.pct}%</span>`
      : "";

    section.innerHTML = `
      <div class="phase-header">
        <h2>${escapeHtml(phase.title)}</h2>
        ${progressHtml}
      </div>
      <p class="phase-covers">${escapeHtml(phase.covers)}</p>
    `;

    phase.rows.forEach((row) => {
      const dayRow = document.createElement("div");
      dayRow.className = "day-row";

      const modulesHtml = row.modules
        .map((mod) => {
          if (!withStatus) {
            return `
              <li class="module-item">
                <span class="module-mark">&ndash;</span>
                <span class="module-name">${escapeHtml(mod.name)}</span>
                ${mod.url ? `<a class="module-link" href="${mod.url}" target="_blank" rel="noopener">module</a>` : ""}
              </li>`;
          }
          const cls = mod.completed ? "done" : "pending";
          const mark = mod.completed ? "&#10003;" : "&#9675;";
          const dateHtml = mod.completed && mod.completed_date
            ? `<span class="module-date">${escapeHtml(mod.completed_date)}</span>`
            : "";
          return `
            <li class="module-item ${cls}">
              <span class="module-mark">${mark}</span>
              <span class="module-name">${escapeHtml(mod.name)}</span>
              ${dateHtml}
              ${mod.url ? `<a class="module-link" href="${mod.url}" target="_blank" rel="noopener">module</a>` : ""}
            </li>`;
        })
        .join("");

      dayRow.innerHTML = `
        <div class="day-meta">
          <span class="date">${escapeHtml(row.date)}</span>
          <span class="day-name">${escapeHtml(row.day)}</span>
        </div>
        <div>
          <p class="day-topic">${escapeHtml(row.topic)}</p>
          <ul class="module-list">${modulesHtml}</ul>
        </div>
      `;
      section.appendChild(dayRow);
    });

    calendarRoot.appendChild(section);
  });
}

function renderProfileAndOverall(result) {
  const p = result.profile || {};
  const rank = result.rank || {};
  const name = [p.first_name, p.last_name].filter(Boolean).join(" ") || p.handle || "Trainee";

  profileSummaryEl.hidden = false;
  profileSummaryEl.innerHTML = `
    <p class="name">${escapeHtml(name)}</p>
    ${p.company ? `<span class="stat">${escapeHtml(p.company)}</span>` : ""}
    ${rank.rank_label ? `<span class="stat"><strong>${escapeHtml(rank.rank_label)}</strong></span>` : ""}
    ${rank.points != null ? `<span class="stat"><strong>${rank.points.toLocaleString()}</strong> pts</span>` : ""}
    ${rank.badges != null ? `<span class="stat"><strong>${rank.badges}</strong> badges earned overall</span>` : ""}
  `;

  overallProgressEl.hidden = false;
  overallProgressEl.innerHTML = `
    <div class="bar-label">
      <span>Assigned modules completed</span>
      <span>${result.overall.done} / ${result.overall.total} &mdash; ${result.overall.pct}%</span>
    </div>
    <div class="bar-track"><div class="bar-fill" style="width:${result.overall.pct}%"></div></div>
  `;
}

async function loadCalendar() {
  const res = await fetch("/api/calendar");
  if (!res.ok) {
    loadingNote.textContent = "Couldn't load the training calendar. Is data/calendar.json present?";
    return;
  }
  baseCalendar = await res.json();
  loadingNote.remove();
  renderCalendar(baseCalendar, { withStatus: false });
}

async function checkProgress(profileValue, { mock } = {}) {
  lookupError.hidden = true;
  checkBtn.disabled = true;
  checkBtn.textContent = "Checking\u2026";
  try {
    const url = `/api/progress?profile=${encodeURIComponent(profileValue || "demo")}${mock ? "&mock=1" : ""}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Something went wrong checking that profile.");
    }
    renderProfileAndOverall(data);
    renderCalendar(data, { withStatus: true });
  } catch (err) {
    lookupError.hidden = false;
    lookupError.textContent = err.message;
  } finally {
    checkBtn.disabled = false;
    checkBtn.textContent = "Check progress";
  }
}

lookupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const value = profileInput.value.trim();
  if (!value) {
    lookupError.hidden = false;
    lookupError.textContent = "Enter a Trailhead profile URL or handle first.";
    return;
  }
  checkProgress(value, { mock: false });
});

demoBtn.addEventListener("click", () => {
  profileInput.value = "demo-trailblazer";
  checkProgress("demo-trailblazer", { mock: true });
});

loadCalendar();
