"""A read-only, side-by-side view of a negotiation, for watching and for the demo video.

Switch and Mattermost remain the system of record. Mattermost shows one room at a time, and the
point of this project is what each side can and cannot see, so this page shows the rooms next to
each other. In real use nobody would hold all three views: it reads with the demo's credentials.

    python -m counterpart.console     # then open http://127.0.0.1:8090
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .clauses import AGENDA, CLAUSES, describe
from .config import load_env
from .demo import Person
from .protocol import parse

PORT = 8090
HIDDEN = ("added to the channel", "joined the channel", "removed from the channel","Mention @", "tag @", "me when you", "you need me")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Counterpart</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--ink:#1c2230;--muted:#5b6475;--line:#d8dce4;--paper:#f6f7f9;--white:#fff;--acme:#17603f;--bolt:#7a3d0c;--deal:#27457a}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--paper);display:flex;flex-direction:column}
header{display:flex;align-items:baseline;gap:12px;padding:10px 16px;background:var(--white);border-bottom:1px solid var(--line)}
h1{font-size:16px;margin:0}header p{margin:0;color:var(--muted)}
#terms{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border-bottom:1px solid var(--line)}
.term{background:var(--white);padding:8px 12px;min-width:0}.term b{display:block;font-size:12px;color:var(--muted);font-weight:600}
.term span{font-size:15px;font-weight:600}.term.open span{color:var(--muted);font-weight:400}
main{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1.35fr 1fr;gap:1px;background:var(--line)}
section{display:flex;flex-direction:column;min-height:0;background:var(--paper)}
h2{margin:0;padding:8px 12px;font-size:13px;color:#fff}
h2 small{display:block;font-weight:400;opacity:.9;font-size:12px}
.acme h2{background:var(--acme)}.bolt h2{background:var(--bolt)}.deal h2{background:var(--deal)}
.feed{flex:1;overflow-y:auto;padding:10px 12px}
.post{background:var(--white);border:1px solid var(--line);border-radius:6px;padding:7px 10px;margin:0 0 7px;overflow-wrap:anywhere;white-space:pre-wrap}
.post code{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}
.ask{border-left:4px solid #b4530a}.ok{border-left:4px solid #17603f}.no{border-left:4px solid #b3261e}
@media(max-width:900px){main{grid-template-columns:1fr;overflow:auto}section{min-height:60vh}#terms{grid-template-columns:1fr 1fr}}
</style></head><body>
<header><h1>Counterpart</h1><p>Each column shows only what that side can see. Limits never cross into the middle.</p></header>
<div id="terms"></div>
<main>
<section class="acme"><h2>Acme chamber<small>Acme Counsel, Priya, Arjun. Negotiator not admitted.</small></h2><div class="feed" id="acme-chamber"></div></section>
<section class="deal"><h2>Deal room<small>Both companies can read this.</small></h2><div class="feed" id="deal-room"></div></section>
<section class="bolt"><h2>Bolt chamber<small>Bolt Counsel, Daniel. Negotiator not admitted.</small></h2><div class="feed" id="bolt-chamber"></div></section>
</main>
<script>
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function fmt(s){return esc(s).replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')}
function cls(s){if(/Decision needed|Heads up/.test(s))return'ask';if(/^\\*\\*Agreed|Deal sealed|^Recorded/.test(s))return'ok';if(/only @|SYSTEM OVERRIDE/.test(s))return'no';return''}
let last={};
async function tick(){
  const data=await (await fetch('/state')).json();
  document.getElementById('terms').innerHTML=data.terms.map(t=>`<div class="term ${t.value?'':'open'}"><b>${esc(t.title)}</b><span>${esc(t.value||'Open')}</span></div>`).join('');
  for(const room of ['acme-chamber','deal-room','bolt-chamber']){
    const posts=data.rooms[room],key=posts.length;
    if(last[room]===key)continue;last[room]=key;
    const el=document.getElementById(room);
    el.innerHTML=posts.map(p=>`<p class="post ${cls(p)}">${fmt(p)}</p>`).join('');
    el.scrollTop=el.scrollHeight;
  }
}
tick();setInterval(()=>tick().catch(()=>{}),1500);
</script></body></html>"""


class Views:
    def __init__(self) -> None:
        password = load_env()["MATTERMOST_USER_PASSWORD"]
        self.priya = Person("priya", password)
        self.daniel = Person("daniel", password)
        self.start = self.latest_start()

    def latest_start(self) -> int:
        """Show only the current deal: everything from the Clerk's latest opening onward."""
        posts = self.priya.read("deal-room")
        indexes = [i for i, post in enumerate(posts) if post.startswith("**Master Services Agreement")]
        return indexes[-1] if indexes else 0

    def state(self) -> dict:
        self.start = self.latest_start()
        deal = self.priya.read("deal-room")[self.start:]
        agreed: dict[str, float | str] = {}
        for post in deal:
            for tag in parse(post):
                if tag.verb == "ACCEPT" and tag.clause:
                    agreed[tag.clause] = tag.value
        clean = lambda posts: [p for p in posts if p.strip() and not any(h in p for h in HIDDEN)]

        def current(posts: list[str]) -> list[str]:
            """Drop chamber history from earlier deals, which each end with a filed log."""
            ends = [i for i, post in enumerate(posts) if "authority log is filed" in post]
            sealed = any("Deal sealed" in post for post in deal)
            cut = ends[-2] + 1 if sealed and len(ends) > 1 else ends[-1] + 1 if not sealed and ends else 0
            return posts[cut:]

        return {
            "terms": [
                {"title": CLAUSES[k].title, "value": describe(k, agreed[k]) if k in agreed else None} for k in AGENDA
            ],
            "rooms": {
                "deal-room": clean(deal),
                "acme-chamber": current(clean(self.priya.read("acme-chamber"))),
                "bolt-chamber": current(clean(self.daniel.read("bolt-chamber"))),
            },
        }


def main() -> None:
    views = Views()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/state":
                body, kind = json.dumps(views.state()).encode(), "application/json"
            else:
                body, kind = PAGE.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            return

    print(f"Open http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
