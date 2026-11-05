.. SPDX-License-Identifier: AGPL-3.0-or-later

.. _metasearch engine: https://en.wikipedia.org/wiki/Metasearch_engine
.. _Installation guide: https://docs.searxng.org/admin/installation.html
.. _Configuration guide: https://docs.searxng.org/admin/settings/index.html
.. _CONTRIBUTING: https://github.com/searxng/searxng/blob/master/CONTRIBUTING.rst
.. _LICENSE: https://github.com/searxng/searxng/blob/master/LICENSE

.. figure:: https://raw.githubusercontent.com/searxng/searxng/master/client/simple/src/brand/searxng.svg
    :target: https://searxng.org
    :alt: SearXNG
    :width: 512px

SearXNG is a `metasearch engine`_. Users are neither tracked nor profiled.

.. image:: https://img.shields.io/badge/organization-3050ff?style=flat-square&logo=searxng&logoColor=fff&cacheSeconds=86400
    :target: https://github.com/searxng
    :alt: Organization

.. image:: https://img.shields.io/badge/documentation-3050ff?style=flat-square&logo=readthedocs&logoColor=fff&cacheSeconds=86400
    :target: https://docs.searxng.org
    :alt: Documentation

.. image:: https://img.shields.io/github/license/searxng/searxng?style=flat-square&label=license&color=3050ff&cacheSeconds=86400
    :target: https://github.com/searxng/searxng/blob/master/LICENSE
    :alt: License

.. image:: https://img.shields.io/github/commit-activity/y/searxng/searxng?style=flat-square&label=commits&color=3050ff&cacheSeconds=3600
    :target: https://github.com/searxng/searxng/commits/master/
    :alt: Commits

.. image:: https://img.shields.io/weblate/progress/searxng?server=https%3A%2F%2Ftranslate.codeberg.org&style=flat-square&label=translated&color=3050ff&cacheSeconds=86400
    :target: https://translate.codeberg.org/projects/searxng/
    :alt: Translated

Setup
=====

Installation
------------
See the `Installation guide`_.

Configuration
-------------
See the `Configuration guide`_.

AI Features
-----------
SearXNG now ships experimental AI‑powered plugins. Enable them in **Settings → Plugins**:

* **AI Overview** – Generates a concise summary of the top results using a large language model. The plugin POSTs the result snippets to a configurable AI endpoint (e.g., Gemini, OpenAI), which runs a language model to produce a short HTML overview inserted below the results. The endpoint can be self‑hosted or a cloud service, and respects user privacy by only sending public snippets.
* **Calculator** – Computes arithmetic or scientific expressions directly from the search bar.
* **Map View** – Renders geolocation results on an interactive map widget.
* **Infinite Scroll** – Loads additional results automatically, leveraging AI‑enhanced ranking.

These plugins live under ``client/simple/src/js/plugin`` and are optional; the core engine works unchanged without them.

Connect
=======

Community
---------
- Matrix: `#searxng:matrix.org <https://matrix.to/#/#searxng:matrix.org>`_
- GitHub Discussions: https://github.com/searxng/searxng/discussions

Contributing
============

See the `CONTRIBUTING`_ guide for how to submit patches, report bugs, or propose new features.

License
=======

This project is licensed under the GNU Affero General Public License (AGPL-3.0). See the `LICENSE`_ for details.
