// SPDX-License-Identifier: AGPL-3.0-or-later

import { Plugin } from "../Plugin.ts";
import { http, settings } from "../toolkit.ts";

type SourceItem = {
  title?: string;
  url?: string;
  content?: string;
  domain?: string;
};

type ApiResponse = {
  html?: string;
  sources?: SourceItem[];
  error?: string;
};

type Result = {
  element: HTMLElement;
  html?: string;
  sources?: SourceItem[];
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
      return { element: element, html: data.html, sources: data.sources };
    } catch (error) {
      console.error("[ai_overview]", error);
      return { element: element, error: true };
    }
  }

  protected async post({ element, html, sources, error }: Result): Promise<void> {
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

    this.setupCollapsible(element, content);
    this.setupCopyButtons(element, content);
    this.setupCitations(element, sources ?? []);
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
