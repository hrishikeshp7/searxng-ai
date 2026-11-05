// SPDX-License-Identifier: AGPL-3.0-or-later

import { Plugin } from "../Plugin.ts";
import { http, settings } from "../toolkit.ts";

type SourceItem = {
  title?: string;
  url?: string;
  content?: string;
  domain?: string;
};

type ThumbnailItem = {
  img: string;
  url: string;
  title: string;
  domain: string;
};

type UsageItem = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
};

type ApiResponse = {
  html?: string;
  sources?: SourceItem[];
  thumbnails?: ThumbnailItem[];
  related?: string[];
  usage?: UsageItem;
  error?: string;
};

type Result = {
  element: HTMLElement;
  html?: string;
  sources?: SourceItem[];
  thumbnails?: ThumbnailItem[];
  related?: string[];
  usage?: UsageItem;
  error?: boolean;
};

/**
 * Fetches an AI-generated overview of search results asynchronously.
 */
export default class AiOverview extends Plugin {
  public constructor() {
    super("ai_overview");
  }

  protected async run(): Promise<Result | undefined> {
    const element = document.querySelector<HTMLElement>("[data-ai-overview]");
    if (!element) return;

    const { autoTrigger } = element.dataset;
    if (autoTrigger === "false") {
      const generateBtn = element.querySelector<HTMLButtonElement>(".ai-overview-generate-btn");
      if (generateBtn) {
        generateBtn.addEventListener("click", async () => {
          const prompt = element.querySelector<HTMLElement>(".ai-overview-prompt");
          const wrapper = element.querySelector<HTMLElement>(".ai-overview-content-wrapper");
          const disclaimer = element.querySelector<HTMLElement>(".ai-overview-disclaimer");

          prompt?.remove();
          wrapper?.classList.remove("hidden");
          disclaimer?.classList.remove("hidden");

          const res = await this.fetchOverview(element);
          await this.post(res);
        });
      }
      return;
    }

    return this.fetchOverview(element);
  }

  private async fetchOverview(element: HTMLElement): Promise<Result> {
    const { url, payload, sig } = element.dataset;
    if (!(url && payload && sig)) return { element: element, error: true };

    try {
      const res = await http("POST", url, {
        body: new URLSearchParams({ payload: payload, sig: sig }),
        timeout: 60_000
      });
      const data = (await res.json()) as ApiResponse;
      if (!data.html) return { element: element, error: true };
      return {
        element: element,
        html: data.html,
        sources: data.sources,
        thumbnails: data.thumbnails,
        related: data.related,
        usage: data.usage
      };
    } catch (error) {
      console.error("[ai_overview]", error);
      return { element: element, error: true };
    }
  }

  protected async post({ element, html, sources, thumbnails, related, usage, error }: Result): Promise<void> {
    const content = element.querySelector<HTMLElement>(".ai-overview-content");
    if (!content) return;

    content.classList.remove("ai-overview-loading");
    content.setAttribute("aria-busy", "false");

    if (error || !html) {
      content.textContent = `⚠ ${settings.translations?.ai_overview_error ?? "Could not generate an AI overview."}`;
      content.classList.add("ai-overview-error");
      return;
    }

    content.innerHTML = html;

    this.setupThumbnails(element, thumbnails ?? []);
    this.setupCollapsible(element, content);
    this.setupCopyButtons(element, content);
    this.setupCitations(element, sources ?? []);
    this.setupRelatedQueries(element, related ?? []);
    this.setupTokenMonitor(element, usage);
  }

  private setupTokenMonitor(element: HTMLElement, usage?: UsageItem): void {
    if (!usage?.total_tokens) return;

    const actions = element.querySelector<HTMLElement>(".ai-overview-actions");
    if (!actions || actions.querySelector(".ai-overview-token-badge")) return;

    const today = new Date().toISOString().slice(0, 10);
    const storageKey = "sxng_ai_token_stats";
    const dailyLimit = 200_000;

    let stats = {
      date: today,
      prompt: 0,
      completion: 0,
      total: 0,
      count: 0
    };

    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed && parsed.date === today) {
          stats = {
            date: today,
            prompt: Number(parsed.prompt) || 0,
            completion: Number(parsed.completion) || 0,
            total: Number(parsed.total) || 0,
            count: Number(parsed.count) || 0
          };
        }
      }
    } catch (e) {
      console.warn("[ai_overview] Failed to read token stats", e);
    }

    const currentTotal = usage.total_tokens || 0;
    const currentPrompt = usage.prompt_tokens || 0;
    const currentCompletion = usage.completion_tokens || 0;

    stats.prompt += currentPrompt;
    stats.completion += currentCompletion;
    stats.total += currentTotal;
    stats.count += 1;

    try {
      localStorage.setItem(storageKey, JSON.stringify(stats));
    } catch (e) {
      console.warn("[ai_overview] Failed to save token stats", e);
    }

    const formatK = (n: number) => {
      if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
      if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
      return n.toString();
    };

    const pct = Math.min(100, Math.round((stats.total / dailyLimit) * 100));
    const remaining = Math.max(0, dailyLimit - stats.total);

    const badge = document.createElement("div");
    badge.className = "ai-overview-token-badge";
    if (pct >= 95) {
      badge.classList.add("danger");
    } else if (pct >= 80) {
      badge.classList.add("warning");
    }

    badge.title = [
      `Search: ${currentPrompt.toLocaleString()} in · ${currentCompletion.toLocaleString()} out (${currentTotal.toLocaleString()} tokens)`,
      `Today: ${stats.total.toLocaleString()} / ${dailyLimit.toLocaleString()} tokens (${pct}%, ${remaining.toLocaleString()} left across ${stats.count} searches)`
    ].join("\n");

    const icon = document.createElement("span");
    icon.className = "token-icon";
    icon.textContent = "⚡";

    const text = document.createElement("span");
    text.className = "token-text";
    text.textContent = `${formatK(currentTotal)} · ${formatK(stats.total)}/${formatK(dailyLimit)} (${pct}%)`;

    badge.appendChild(icon);
    badge.appendChild(text);

    actions.prepend(badge);
  }

  private setupThumbnails(element: HTMLElement, thumbnails: ThumbnailItem[]): void {
    if (thumbnails.length === 0) return;

    const wrapper = element.querySelector<HTMLElement>(".ai-overview-content-wrapper");
    if (!wrapper) return;
    if (element.querySelector(".ai-overview-media")) return;

    const mediaRow = document.createElement("div");
    mediaRow.className = "ai-overview-media";

    for (const t of thumbnails) {
      const card = document.createElement("a");
      card.href = t.url;
      card.target = "_blank";
      card.rel = "noreferrer";
      card.className = "ai-media-card";
      card.title = t.title;

      const img = document.createElement("img");
      img.src = t.img;
      img.alt = t.title;
      img.loading = "lazy";

      const domain = document.createElement("span");
      domain.className = "ai-media-domain";
      domain.textContent = t.domain;

      card.appendChild(img);
      card.appendChild(domain);
      mediaRow.appendChild(card);
    }

    wrapper.prepend(mediaRow);
  }

  private setupRelatedQueries(element: HTMLElement, related: string[]): void {
    if (related.length === 0) return;
    if (element.querySelector(".ai-overview-related")) return;

    const container = document.createElement("div");
    container.className = "ai-overview-related";

    for (const q of related) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ai-related-chip";
      btn.dataset.query = q;

      const iconSpan = document.createElement("span");
      iconSpan.className = "ai-related-icon";
      iconSpan.textContent = "🔍";

      const textSpan = document.createElement("span");
      textSpan.textContent = q;

      btn.appendChild(iconSpan);
      btn.appendChild(textSpan);

      btn.addEventListener("click", () => {
        const input = document.querySelector<HTMLInputElement>("#q");
        const form = document.querySelector<HTMLFormElement>("#search");
        if (input && form) {
          input.value = q;
          form.submit();
        }
      });

      container.appendChild(btn);
    }

    const content = element.querySelector<HTMLElement>(".ai-overview-content");
    content?.appendChild(container);
  }

  private setupCollapsible(element: HTMLElement, content: HTMLElement): void {
    const wrapper = element.querySelector<HTMLElement>(".ai-overview-content-wrapper");
    const toggleBtn = element.querySelector<HTMLButtonElement>(".ai-overview-toggle-btn");
    const toggleText = toggleBtn?.querySelector<HTMLElement>(".toggle-text");

    if (!(wrapper && toggleBtn)) return;

    if (content.scrollHeight > 240) {
      wrapper.classList.add("collapsed");
      toggleBtn.style.display = "inline-flex";

      toggleBtn.addEventListener("click", () => {
        const isCollapsed = wrapper.classList.toggle("collapsed");
        toggleBtn.classList.toggle("expanded", !isCollapsed);
        if (toggleText) {
          toggleText.textContent = isCollapsed
            ? (settings.translations?.show_more ?? "Show more")
            : (settings.translations?.show_less ?? "Show less");
        }
      });
    }
  }

  private setupCopyButtons(element: HTMLElement, content: HTMLElement): void {
    const copyBtn = element.querySelector<HTMLButtonElement>(".ai-overview-copy-btn");
    if (copyBtn) {
      copyBtn.style.display = "inline-flex";
      copyBtn.addEventListener("click", async () => {
        const clone = content.cloneNode(true) as HTMLElement;
        clone.querySelector(".ai-overview-sources")?.remove();
        clone.querySelector(".ai-overview-related")?.remove();
        const text = clone.innerText.trim();
        if (!text) return;

        try {
          await navigator.clipboard.writeText(text);
          copyBtn.classList.add("copied");
          const origTitle = copyBtn.getAttribute("title") ?? "";
          copyBtn.setAttribute("title", settings.translations?.copied ?? "Copied!");
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            copyBtn.setAttribute("title", origTitle);
          }, 1800);
        } catch (e) {
          console.error("[ai_overview] Copy failed", e);
        }
      });
    }

    const preElements = content.querySelectorAll<HTMLElement>("pre");
    for (const pre of preElements) {
      const code = pre.querySelector("code");
      if (!code) continue;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ai-code-copy-btn";
      btn.textContent = settings.translations?.copy ?? "Copy";
      btn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(code.innerText.trim());
          btn.textContent = settings.translations?.copied ?? "Copied!";
          setTimeout(() => {
            btn.textContent = settings.translations?.copy ?? "Copy";
          }, 1800);
        } catch (e) {
          console.error("[ai_overview] Code copy failed", e);
        }
      });
      pre.appendChild(btn);
    }
  }

  private setupCitations(element: HTMLElement, sources: SourceItem[]): void {
    const popover = document.createElement("div");
    popover.className = "ai-citation-popover";
    element.appendChild(popover);

    let hideTimeout: ReturnType<typeof setTimeout> | undefined;

    const showPopover = (citationLink: HTMLElement, sourceIndex: number) => {
      if (hideTimeout !== undefined) clearTimeout(hideTimeout);
      const source = sources[sourceIndex - 1];
      if (!source) return;

      const chip = element.querySelector<HTMLElement>(`.ai-source-chip[data-source="${sourceIndex}"]`);
      chip?.classList.add("highlighted");

      popover.innerHTML = `
        ${source.domain ? `<div class="ai-citation-popover-domain">${this.escapeText(source.domain)}</div>` : ""}
        ${source.title ? `<div class="ai-citation-popover-title">${this.escapeText(source.title)}</div>` : ""}
        ${source.content ? `<div class="ai-citation-popover-snippet">${this.escapeText(source.content)}</div>` : ""}
      `;

      const linkRect = citationLink.getBoundingClientRect();
      const parentRect = element.getBoundingClientRect();

      let left = linkRect.left - parentRect.left;
      const top = linkRect.bottom - parentRect.top + 6;

      if (left + 260 > parentRect.width) {
        left = Math.max(10, parentRect.width - 270);
      }

      popover.style.left = `${left}px`;
      popover.style.top = `${top}px`;
      popover.classList.add("visible");
    };

    const hidePopover = () => {
      hideTimeout = setTimeout(() => {
        popover.classList.remove("visible");
        const chips = element.querySelectorAll(".ai-source-chip.highlighted");
        for (const c of chips) {
          c.classList.remove("highlighted");
        }
      }, 150);
    };

    const citationElements = element.querySelectorAll<HTMLElement>(".ai-citation");
    for (const citation of citationElements) {
      const idx = Number.parseInt(citation.dataset.citation ?? "0", 10);
      if (idx > 0) {
        citation.addEventListener("mouseenter", () => showPopover(citation, idx));
        citation.addEventListener("mouseleave", hidePopover);
        citation.addEventListener("focus", () => showPopover(citation, idx));
        citation.addEventListener("blur", hidePopover);
      }
    }
  }

  private escapeText(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}
