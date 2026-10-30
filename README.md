# INSIGNIA — project site

A world-building art project told through a serialized **novel**, a **gallery**, **films** (YouTube)
and a curated **Archive** (an in-world encyclopedia). Everything links to everything: a word in a
chapter links to its Archive entry, and every Archive entry lists the chapters, works and films it
appears in.

Three visual modes share one design system:

| Mode | Used for | Modelled on |
|---|---|---|
| **Shell** | home, novel index, gallery, films | Nothing — dot-matrix type, frosted containers, mono labels, `#F4F4F4` + one red |
| **Reader** | chapters, About | Medium — 680px column, 20/32 serif body, sans headings |
| **Archive** | `/wiki/` | Wikipedia — infobox, contents sidebar, references, navboxes, categories, red links |

Light and dark themes are built in (toggle in the header; follows the system by default).

---

## Quick start

Requires Python 3.9+ with `markdown`, `jinja2` and `pyyaml` (already installed on this machine;
elsewhere: `pip install -r requirements.txt`).

```bash
python3 build.py serve
```

Open <http://localhost:8000>. Every time you save a file in `content/`, `templates/`, `assets/` or
`static/` the site rebuilds — just refresh. (Restart the command after editing `build.py` itself.)

```bash
python3 build.py
```

builds the finished site into `dist/`, ready to upload anywhere. The build also lists any
`[[links]]` to Archive entries you haven't written yet.

---

## Where things live

```
content/
  site.yaml               site title, menu, home page, Archive main page, footer
  novel/<book>/           one folder per book
    _book.yaml            title, cover, synopsis
    01-first-chapter.md   chapters, in file-name order
  wiki/*.md               Archive entries (one file each)
  navboxes.yaml           the link boxes at the bottom of Archive entries
  gallery.yaml            gallery works
  films.yaml              YouTube films
  pages/*.md              standalone pages (About → /about/)
static/                   images and files, copied as-is (static/images/x.jpg → /images/x.jpg)
templates/                page layouts (Jinja2)
assets/css/               styles — colours and fonts are all in 01-tokens.css
assets/js/site.js         search, link previews, lightbox, video, theme
build.py                  the builder
md2xtc/                   the Xteink converter behind the "Download .xtc" button on book pages
```

The images in `static/images/art/` are generated placeholders, and the three films are Blender
open movies used as stand-ins. Replace both with your own work.

---

## Writing

Every `.md` file starts with a **front matter** block between `---` lines, then Markdown.

### Edit in the browser

Run `python build.py serve`, then open <http://localhost:8000/editor/> or select
**소설 편집** in the navigation. Book pages and chapters also link to their editor.

- Select a book to edit its title, author, genres, cover, status and synopsis.
- Select a chapter to edit its heading, alternate title, subtitle, date and Markdown
  body. **미리보기** uses the same Markdown renderer as the reading pages, including
  Archive links and footnotes. The formatting buttons insert Markdown.
- **새 챕터** creates a chapter when you save it. New chapters start as drafts;
  clear **초안으로 보관** to include them in the reading pages.
- **저장** (Ctrl/Cmd + S) writes the source file and rebuilds the site. Chapter
  filenames and existing reading URLs stay stable when their headings change.
  Other front matter fields are preserved. Previous file contents are backed up
  in `.cache/editor/<book>/`; a failed build restores the previous source.
- Unsaved changes are temporarily kept in this browser. On returning to the
  manuscript, choose **이어 쓰기** to recover them. This does not replace saving.
  If the source was edited elsewhere, saving stops to avoid overwriting it.

The development editor binds to loopback by default. Production uses the shared
wiki authentication gateway described below. Static builds exclude the editor.

### 세계관 타임라인 (로컬 개발)

`python3 build.py serve` 실행 후 <http://localhost:8000/editor/timeline/>을 열거나
**콘텐츠 관리 → 타임라인**으로 이동합니다. 호스트 서버 배포는 별도로 수행해야 하며,
이 기능을 추가하는 것만으로 서버나 기존 위키 연표가 변경되지는 않습니다.

- 연도·제목을 입력하고 **사건 저장**을 누르면 백엔드에 저장됩니다. 월·일자와 설명은
  선택 사항입니다. 원문에 월이 없으면 **미정**으로 두고, `1990년대 초`나 `2010 이후`처럼
  모호한 시점은 **시점 표기**에 보존합니다. 정렬은 입력한 연도를 기준으로 합니다.
  연도는 -999999~999999까지 사용할 수 있고, 일자를 입력하면
  그레고리력 기준으로 검증합니다. 같은 달의 일자 미정 사건이 먼저 정렬됩니다.
- 연도별 열에 사건이 날짜순으로 자동 배치됩니다. 배경의 큰 연도, 연도 탐색과
  사건·연도 검색으로 위치를 찾을 수 있습니다. 빈 공간 드래그로 이동하고 휠이나
  확대/축소 버튼으로 배율을 바꿉니다. 터치에서는 빈 공간 드래그·두 손가락 확대를 지원합니다.
- 상단 **가로 / 세로** 버튼으로 보기 방향을 바꿀 수 있습니다. 세로 보기에서는
  연도별 사건이 위에서 아래로 이어지고 휠로 스크롤합니다. `Ctrl`/`Cmd`+휠이나
  확대/축소 버튼으로 배율을 바꿀 수 있습니다. 두 보기는 같은 사건을 편집하며,
  전환해도 작성 중인 내용이 유지됩니다. 마지막 보기 방향은 브라우저에 기억됩니다.
- **전체 보기** / `F`, **사건 추가** / `N`, 확대 `+`, 축소 `-` 단축키를 지원합니다.
  캔버스에 포커스가 있을 때 방향키로 이동할 수 있습니다. 사건을 누르면 오른쪽
  패널에서 수정·삭제할 수 있고, 저장하면 바뀐 날짜로 이동합니다.
- 데이터 원본은 `INSIGNIA_DATA_ROOT`(기본: 프로젝트 폴더)의
  `timeline-data/timeline.json`입니다. 사건을 저장하면 날짜순으로 정돈된 UTF-8 JSON을
  원자적으로 갱신하므로 Git에서 내용 변경을 비교·커밋·복원할 수 있습니다.
  새로 체크아웃한 저장소에서도 이 파일을 바로 읽습니다. 파일에는 제목과 모든 사건의
  날짜·시점 표기·설명·색상·출처 링크가 포함되며, 저장 횟수나 시각은 기록하지 않습니다.
  Git 복원이나 직접 파일 수정도 내용 기반 버전으로 감지해 오래된 창의 덮어쓰기를 막습니다.
- 기존 `.private/timeline.sqlite3`만 있는 경우 첫 조회에서 JSON으로 한 번 이전합니다.
  SQLite 파일은 백업으로 남겨 두며 JSON이 생긴 뒤에는 읽거나 갱신하지 않습니다.
  `.private/`의 잠금 파일·기존 DB·백업은 계속 Git에서 제외됩니다.
  변경을 기록하려면 `git add timeline-data/timeline.json` 후 커밋하세요. 저장 자체가
  Git 커밋이나 push를 실행하지는 않습니다. 공개 저장소에 push하면 연표 데이터도 공개됩니다.
- `timeline-data/`는 공개 `dist/`·검색·Docker 빌드 컨텍스트에 포함되지 않습니다.
  기존 Compose 구성처럼 체크아웃 전체를 `/workspace`에 마운트하면 백엔드가 해당
  JSON을 읽고 저장합니다. 웹사이트에서는 계속 로그인한 사용자의 편집 API로만 조회합니다.
- HTML은 `/editor/timeline/`, API는 `/__editor/api/timeline`과
  `/__editor/api/timeline/save`를 사용합니다. 기존 `/editor/`와 같은 로그인 게이트웨이
  보호를 받습니다. 운영 모드에서는 조회·저장 모두 인증 프록시 토큰이 필요하고,
  게이트웨이는 로그인한 계정만 통과시킵니다. 기존 개발 모드에서는 로그인 없이
  루프백 주소에서만 사용할 수 있습니다. 개발 서버를 외부에 직접 공개하지 마세요.

타임라인은 하나의 비공개 공유 작업판이며, 기존 위키의 공개 연표와 별도로 저장됩니다.
이 저장소에는 별도의 계정·비밀번호 저장소를 추가하지 않습니다.

### Books

The home page and `/novel/` share a thumbnail grid, ordered by `order` in each book's
`_book.yaml`. The Ground Zero is first, followed by three books titled `제목 미정`.
The existing chapters remain in `content/novel/the-anger/`; the two empty book folders
show a coming-soon page until chapters are added. Edit each `_book.yaml` to set its
title, cover, synopsis and status. Set genres as a list, such as
`genres: [금융 스릴러, 전쟁경제, 정치]`, to display them on thumbnails and book pages.
Number chapter filenames to set their reading order.
Chapter headings use `heading` in front matter when set by the editor; otherwise
they use the filename without `.md` or its leading ordering number.
The front matter `title` appears underneath in smaller text when it differs from
the main heading; `subtitle` remains a separate descriptive line. Both names are searchable.

### A chapter — `content/novel/the-quiet-signal/04-next-chapter.md`

```markdown
---
title: The Next Chapter
subtitle: One line that appears under the title.
date: 2026-10-01
---
First paragraph. Add `dropcap: true` to the front matter for a large dot-matrix first letter.

She climbed toward the [[pylon]] above [[Halden]].
```

Optional: `number: "00"` and `label: Prologue` for unnumbered chapters, `cover:` for a social image,
`draft: true` to hide it.

### An Archive entry — `content/wiki/maren-oake.md`

```markdown
---
title: Maren Oake
description: Warden of the Lantern Guild          # short line under search results
aliases: [the Warden]                            # other names that [[link]] here
sort: Oake, Maren                                # alphabetical position in the index
categories: [Characters]
navbox: world                                    # a box from navboxes.yaml
hatnote: "Not to be confused with [[Oake Street]]."
date: 2026-10-01
infobox:
  image: /images/maren.jpg
  caption: Maren Oake in 212 PD
  color: "#e4dcef"                               # colour of the header rows
  rows:
    - header: Personal
    - Born: 140 PD, [[Halden]]
    - Office: "[[Lantern Guild]] Warden"         # quote values that START with [[
---
**Maren Oake** is the Warden of the [[Lantern Guild]].[^1]

## Early life
...

[^1]: *The Book of Lamps*, folio 3.
```

Headings (`##`) become the contents sidebar; `[^1]` footnotes become the **References** section.

### Links

| You write | You get |
|---|---|
| `[[Halden]]` | link to the entry titled *Halden* (also matches its `aliases`) |
| `[[Halden\|the city]]` | same link, different text |
| `[[Pylon]]s` | link text "Pylons" |
| `[[Pylon#The seventh lamp]]` | link to a section |
| `[[Someone New]]` | **red link** until that entry exists (plain text in chapters) |

Links work in chapters, entries, infoboxes, gallery/film descriptions and `site.yaml`.
Hovering a link shows a preview of the entry.

### Images

```markdown
![alt text](/images/harbour.jpg "Caption under the image")
![alt text](/images/harbour.jpg "Caption"){.wide}     chapters: wider than the text
![alt text](/images/harbour.jpg "Caption"){.full}     chapters: full screen width
![alt text](/images/harbour.jpg "Caption"){.left}     Archive: float left (default is right)
![alt text](/images/harbour.jpg "Caption"){.center}   Archive: centred, not floated
```

### Video (anywhere in Markdown, on its own line)

```markdown
[[youtube:dQw4w9WgXcQ|Optional caption]]
```

Videos load from YouTube (privacy-enhanced mode) only when someone presses play.

### Pull quote and scene break (chapters)

```markdown
> A line to set large.
{.pull}

---
```

### Gallery and films

See the comments at the top of `content/gallery.yaml` and `content/films.yaml`. Put the Archive
entries a work depicts in `wiki: [...]` — the entries then list the work under *Appearances*.

### E-reader download (.xtc)

Every book page has a **Download .xtc** button: the whole book as one file for Xteink e-readers,
made by `md2xtc/` during the build. It has a title page and one chapter per new page (plus a
contents page when a book has more than one chapter). Wiki links become plain text, and videos
are left out.

- Text size and other settings: `xtc:` in `content/site.yaml`. `xtc: false` removes the button.
- Needs `pillow`, `numpy` and `markdown-it-py`, and a Korean font (Noto CJK; on Debian/Ubuntu
  `apt install fonts-noto-cjk`). Without them the site still builds, with no button and a warning.
- Typesetting takes a few seconds, so each finished file is kept in `.cache/xtc/` and made again
  only when its book changes.
- `md2xtc/` is a copy of the converter in `~/Documents/notes/md2xtc`, with one addition: the
  `breaks` setting, which keeps every new line as a line break, as the reader pages do.

---

## Look and feel

- **Colours, fonts, radii** — `assets/css/01-tokens.css`. The Nothing red is `--accent`.
- **Fonts** (Google Fonts): *Doto* (dot matrix), *Geist* / *Geist Mono* (UI and labels),
  *Source Serif 4* (reading), with *Noto Sans KR* / *Noto Serif KR* for Korean text.
  If the site is mainly in Korean, set `language: ko` in `site.yaml`.
- **Layouts** — `templates/`. Home tiles and the Archive main page are configured in `site.yaml`.

---

## Publishing

The site is static HTML, so any static host works. The build command is `python3 build.py`
and the output folder is `dist`.

- **Your own Mac mini, via Cloudflare Tunnel.** See [deploy/README.md](deploy/README.md).
  After a one-time setup, publishing is a single command: `deploy/publish.sh you@mac-mini.local`.
- **Tailscale Funnel on Windows** — build the site locally, run
  `python deploy/serve_local.py` to serve `dist` on `127.0.0.1:8765`, then run
  `tailscale funnel --bg 8765` after enabling Funnel for the device in your tailnet.
  This computer has an `Insignia Static Site` scheduled task that starts the local
  server at sign-in; rebuild `dist` after changing the site.
- **Netlify / Cloudflare Pages** — build command `pip install -r requirements.txt && python3 build.py`,
  output directory `dist`.


## Production: wiki login and Docker

The public site is <https://insignia.mastercable-cloud.site>. **위키** in the desktop,
mobile and footer navigation opens <https://insignia-wiki.mastercable-cloud.site>.
Reading remains public. The novel editor, unpublished manuscript API, previews and
saves require the same Cloudflare email verification and password as wiki editing.
Login starts at the wiki; a successful login there also establishes the novel session.
An existing wiki login returns to the novel editor without another password prompt.
The 30-day remember setting and logout apply to both sites.

Run the production stack from the sibling `insignia-wiki` repository's `compose.yaml`.
It builds this Dockerfile, mounts this repository at `/workspace`, and connects the
Python server to the Node authentication gateway over a private Docker network.
No host port is published. Both containers receive the same random gateway token
as a Docker secret; never commit or print this token. The Python server requires it
for editor HTML and manuscript requests, even from loopback. External write origins
and sessions are verified by the gateway before requests reach Python.

`INSIGNIA_DATA_ROOT` selects the writable content/static/dist/cache directory;
code, templates and assets are loaded from the image. `INSIGNIA_BIND` defaults to
`127.0.0.1`; an external binding requires `INSIGNIA_PROXY_TOKEN_FILE`. The production
container sets `INSIGNIA_BIND=0.0.0.0` behind the private gateway. A failed initial
production build aborts startup. Do not expose this Python service directly or run a
second editor against the same content directory.

The wiki owns the only password database. A short-lived, single-use handoff bound
to the browser and exact novel origin establishes a separate host-only session cookie.
No password or Cloudflare identity token is sent to Python. Both domains route through
`http://insignia-wiki:4173` on the existing Cloudflare Docker tunnel; the wiki login
paths retain their Cloudflare Access policy. See the wiki README for account management,
secret generation, configuration and rollback.

The three Ground Zero Markdown chapters and the cafe illustration were synchronized
from the already-public October 12 deployment before switching hosting. This preserves
the published prose and formatting instead of replacing it with older GitHub chapters.
Editing backups remain in `.cache/editor/` and are never served publicly.

Validate with `python -m unittest discover -s tests -v`. Tests use temporary manuscripts
and cover real saves, stale revisions, rollback, drafts, private gateway authentication,
encoded editor paths, HEAD requests and cross-origin rejection. The sibling wiki tests
cover the shared login flow, one-time code expiry/replay, session migration and logout.

## Content Studio and publication controls

After signing in, open **콘텐츠 관리** at `/editor/manage/`. The studio provides:

- **공개 설정**: public/private switches and labels for Novel, Gallery, Films, Archive, the external wiki, and About. Hidden sections lose their navigation, routes, search results and homepage features. The external wiki remains available to its authenticated owner.
- **Novel**: create books, edit book information and hide a whole book including chapters and XTC downloads. **챕터 편집** opens the existing manuscript editor, with per-chapter drafts.
- **Gallery**: add/edit works, images and thumbnails, alt text, media, tags, links and Markdown descriptions. PNG/JPG/WebP/GIF uploads are verified and limited to 20MB.
- **Films**: add/edit YouTube videos, thumbnails, durations and descriptions. YouTube's own visibility must be managed on YouTube.
- **Archive / About**: create and edit Markdown documents and their basic metadata while preserving other front matter.
- **위키**: open the existing wiki editor, which now provides document-level publication settings.

New studio items and new chapters start private. Existing publication choices stay unchanged. Preview content before saving; saves immediately rebuild the public output. Revision checks prevent overwriting another edit. Exact prior bytes are backed up in `.cache/editor/content/`, and failed builds restore the source and preserve the previous served output.

Private items are filtered before rendering, cross-links, feeds, search and XTC generation. Images/uploads not referenced by public output are removed from the served tree; the originals remain in `static/`. Assets shared by another public item remain public. Authenticated previews can load original images through `/__editor/media`; this endpoint and every `/__editor/` API require gateway authentication in production. Unattached uploads are private.

Live section switches are in `content/publication.json`, atomically saved with the content build. The Node gateway mounts `content/` read-only to apply the external wiki switch without restarting. Uploaded files are ignored by Git; back up the whole mounted content/static/cache directories. The tracked `content/publication.json` stores menu labels and public/private switches so fresh checkouts preserve the intended public scope; saves in the studio modify that file and should be reviewed before committing. Credentials and session data remain local to the authentication gateway. This website's privacy controls do not change material already published in GitHub or other external services. Do not push private manuscripts or their backups to a public repository.

Development `--drafts` remains loopback-only. The production gateway refuses draft-inclusive builds. The management UI and private original files are omitted from a normal static build. Public static deployments cannot use the authenticated editor; deploy the Docker stack for these controls.

### Trash and restore

Existing items have **휴지통으로 이동** in their editor. This covers books, chapters,
gallery works, films, Archive documents and About pages. The manuscript editor also
provides this action for the selected book/chapter. Deleted entries disappear from
public output and regular editing lists; their source, media and backups remain stored.
Moving a book to the trash hides all its chapters and download files together.

Open **휴지통** in Content Studio to restore an item. Restored items always return
**private**, so review them before explicitly publishing. For a deleted book, restore
the book first to manage any chapters separately moved to the trash. The external wiki
has its own authenticated trash page and document editor action, linked from the studio.

Trash and restore check the current source revision and rebuild atomically; failed
builds roll back the change. No automatic purge or permanent deletion is implemented.
