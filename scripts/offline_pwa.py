import hashlib
import json
from html import escape
from pathlib import Path

from mkdocs.utils import get_relative_url


EXCLUDED_PATHS = {
    ".DS_Store",
    "manifest.webmanifest",
    "sw.js",
    "sitemap.xml.gz",
}

EXCLUDED_SUFFIXES = (
    ".map",
)

CACHE_PREFIX = "jimny-manual-"

DEFAULT_SETTINGS = {
    "enabled": True,
    "precache_files": False,
    "precache_images": True,
    "precache_print_page": False,
    "precache_source_maps": False,
}


def on_post_page(output, page, config):
    settings = _settings(config)
    if not settings["enabled"]:
        return output

    manifest_url = get_relative_url("manifest.webmanifest", page.url)
    title = escape(config.site_name)
    tags = f"""
      <link rel="manifest" href="{manifest_url}">
      <meta name="theme-color" content="#ffffff">
      <meta name="apple-mobile-web-app-capable" content="yes">
      <meta name="apple-mobile-web-app-title" content="{title}">
    """

    return output.replace("</head>", f"{tags}\n  </head>", 1)


def on_post_build(config):
    site_dir = Path(config.site_dir)
    settings = _settings(config)

    if not settings["enabled"]:
        _write_cleanup_service_worker(site_dir)
        return

    urls = []
    digest = hashlib.sha256()

    for path in sorted(site_dir.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(site_dir).as_posix()
        if _is_excluded(rel, settings):
            continue

        digest.update(rel.encode("utf-8"))
        digest.update(path.read_bytes())
        urls.append(_url_for(rel))

    version = digest.hexdigest()[:16]
    _write_manifest(site_dir, config)
    _write_service_worker(site_dir, version, urls)


def _settings(config):
    raw = config.extra.get("offline_pwa", {})
    if isinstance(raw, bool):
        return {**DEFAULT_SETTINGS, "enabled": raw}
    if raw is None:
        raw = {}

    return {
        key: bool(raw.get(key, value))
        for key, value in DEFAULT_SETTINGS.items()
    }


def _is_excluded(path, settings):
    excluded_prefixes = []
    if not settings["precache_files"]:
        excluded_prefixes.append("files/")
    if not settings["precache_images"]:
        excluded_prefixes.append("images/")
    if not settings["precache_print_page"]:
        excluded_prefixes.append("print_page/")

    return (
        path in EXCLUDED_PATHS
        or Path(path).name in EXCLUDED_PATHS
        or any(path.startswith(prefix) for prefix in excluded_prefixes)
        or (
            not settings["precache_source_maps"]
            and any(path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)
        )
    )


def _url_for(path):
    if path == "index.html":
        return "./"
    if path.endswith("/index.html"):
        return path.removesuffix("index.html")
    return path


def _write_manifest(site_dir, config):
    manifest = {
        "name": config.site_name,
        "short_name": "Jimny JB74W",
        "description": config.site_description or config.site_name,
        "lang": "ru",
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#ffffff",
    }

    (site_dir / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_service_worker(site_dir, version, urls):
    urls_json = json.dumps(urls, ensure_ascii=False, indent=2)
    source = f"""const CACHE_PREFIX = "{CACHE_PREFIX}";
const CACHE_NAME = `${{CACHE_PREFIX}}{version}`;
const PRECACHE_URLS = {urls_json};

const sameScope = (request) => {{
  const scope = new URL(self.registration.scope);
  const url = new URL(request.url);
  return url.origin === scope.origin && url.pathname.startsWith(scope.pathname);
}};

const cacheRequest = (url) => new Request(new URL(url, self.registration.scope), {{
  cache: "reload",
}});

self.addEventListener("install", (event) => {{
  event.waitUntil((async () => {{
    const cache = await caches.open(CACHE_NAME);
    await precacheAll(cache, PRECACHE_URLS);
    await self.skipWaiting();
  }})());
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil((async () => {{
    const names = await caches.keys();
    await Promise.all(names.map((name) => (
      name === CACHE_NAME || !name.startsWith(CACHE_PREFIX)
        ? undefined
        : caches.delete(name)
    )));
    await self.clients.claim();
  }})());
}});

self.addEventListener("fetch", (event) => {{
  const request = event.request;
  if (request.method !== "GET" || !sameScope(request)) return;

  if (request.mode === "navigate") {{
    event.respondWith(networkFirst(request));
    return;
  }}

  event.respondWith(cacheFirst(request));
}});

async function networkFirst(request) {{
  const cache = await caches.open(CACHE_NAME);

  try {{
    const response = await fetch(request);
    if (response && response.ok) {{
      await cache.put(request, response.clone());
    }}
    return response;
  }} catch (_) {{
    return await cache.match(request, {{ ignoreSearch: true }})
      || await cache.match(new URL("./", self.registration.scope), {{ ignoreSearch: true }})
      || Response.error();
  }}
}}

async function precacheAll(cache, urls) {{
  const queue = [...urls];
  const workers = Array.from({{ length: 6 }}, async () => {{
    while (queue.length) {{
      const url = queue.shift();
      try {{
        await cache.add(cacheRequest(url));
      }} catch (_) {{}}
    }}
  }});

  await Promise.all(workers);
}}

async function cacheFirst(request) {{
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request, {{ ignoreSearch: true }});
  if (cached) return cached;

  const response = await fetch(request);
  if (response && response.ok) {{
    await cache.put(request, response.clone());
  }}
  return response;
}}
"""

    (site_dir / "sw.js").write_text(source, encoding="utf-8")


def _write_cleanup_service_worker(site_dir):
    source = f"""const CACHE_PREFIX = "{CACHE_PREFIX}";

self.addEventListener("install", (event) => {{
  event.waitUntil(self.skipWaiting());
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil((async () => {{
    const names = await caches.keys();
    await Promise.all(names.map((name) => (
      name.startsWith(CACHE_PREFIX) ? caches.delete(name) : undefined
    )));
    await self.registration.unregister();
  }})());
}});
"""

    (site_dir / "sw.js").write_text(source, encoding="utf-8")
