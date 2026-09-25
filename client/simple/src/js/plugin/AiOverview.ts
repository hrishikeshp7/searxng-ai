// SPDX-License-Identifier: AGPL-3.0-or-later

import { Plugin } from "../Plugin.ts";
import { http, settings } from "../toolkit.ts";

type Result = { element: HTMLElement; html?: string; error?: boolean };

/**
 * Fetches a short AI-generated overview of the results and appends it after
 * the regular results have already loaded, so it never delays the search
 * response itself.
 */
export default class AiOverview extends Plugin {
  public constructor() {
    super("ai_overview");
  }

  protected async run(): Promise<Result | undefined> {
    const element = document.querySelector<HTMLElement>("[data-ai-overview]");
    if (!element) return;

    const { url, payload, sig } = element.dataset;
    if (!(url && payload && sig)) return { element: element, error: true };

    try {
      const res = await http("POST", url, {
        body: new URLSearchParams({ payload: payload, sig: sig }),
        timeout: 60_000
      });
      const data = (await res.json()) as { html?: string };
      if (!data.html) return { element: element, error: true };
      return { element: element, html: data.html };
    } catch (error) {
      console.error("[ai_overview]", error);
      return { element: element, error: true };
    }
  }

  protected async post({ element, html, error }: Result): Promise<void> {
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
  }
}
