(() => {
  const root = document.querySelector('[data-content-manager]'); if (!root) return;
  const $ = selector => root.querySelector(selector), base = document.documentElement.dataset.base || '';
  const names = {settings:'공개 설정',books:'Novel · 책과 챕터',gallery:'Gallery · 갤러리 작품',films:'Films · 영상',archive:'Archive · 아카이브 문서',pages:'About · 소개 페이지','world-wiki':'위키 · 문서 관리',trash:'휴지통'};
  const section = {books:'novel',gallery:'gallery',films:'films',archive:'wiki',pages:'about','world-wiki':'insignia-wiki'};
  const schemas = {
    books:[['title','책 제목'],['subtitle','권·시리즈 이름'],['author','작가'],['genres','장르 (쉼표로 구분)'],['status','연재 상태'],['cover','표지 이미지','image'],['synopsis','책 소개','textarea']],
    gallery:[['title','작품 제목'],['image','작품 이미지','image'],['thumb','목록용 이미지 (선택)','image'],['alt','이미지 대체 텍스트'],['medium','제작 기법'],['date','날짜','date'],['tags','태그 (쉼표로 구분)'],['wiki','연결할 Archive 문서 (쉼표로 구분)'],['description','작품 설명','textarea']],
    films:[['title','영상 제목'],['youtube','YouTube 주소 또는 영상 ID'],['thumbnail','썸네일 (선택)','image'],['duration','재생 시간 (예: 7:44)'],['date','날짜','date'],['wiki','연결할 Archive 문서 (쉼표로 구분)'],['description','영상 설명','textarea']],
    archive:[['title','문서 제목'],['description','요약'],['date','날짜','date'],['categories','분류 (쉼표로 구분)'],['aliases','다른 이름 (쉼표로 구분)'],['body','본문','textarea']],
    pages:[['title','페이지 제목'],['subtitle','부제'],['date','날짜','date'],['body','본문','textarea']],
  };
  let catalog, current = null, kind = 'settings', saved = '', busy = false, sequence = 0, settingsDirty = false;
  const form = $('[data-manager-form]'), error = $('[data-manager-error]');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(endpoint, payload) {
    const response = await fetch(`${base}/__editor/api/content/${endpoint}`, payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-Insignia-Editor':'1'},body:JSON.stringify(payload)});
    let result; try { result = await response.json(); } catch { throw new Error('편집 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'); }
    if (!response.ok) throw new Error(result.error || '저장하지 못했습니다.'); return result;
  }
  function showError(reason) { error.textContent = reason?.message || reason || ''; error.hidden = !error.textContent; if (!error.hidden) error.focus(); }
  function values() {
    const result = {}; for (const input of form.elements) if (input.name) result[input.name] = input.type === 'checkbox' ? input.checked : input.value;
    return result;
  }
  const dirty = () => settingsDirty || (current && JSON.stringify(values()) !== saved);
  function lock(value) { busy = value; root.querySelectorAll('button,input,textarea').forEach(e => e.disabled = value); }
  function status(message) {
    $('[data-manager-status]').textContent = message || (dirty() ? '저장하지 않은 변경 사항이 있습니다.' : '저장됨');
    const privateItem = form.elements.namedItem('draft')?.checked;
    $('[data-publication-badge]').textContent = privateItem ? '비공개' : '공개';
  }
  async function leave() { return !dirty() || window.confirm('저장하지 않은 변경 사항이 있습니다. 이동할까요?'); }
  function field(key, label, type, value) {
    const container = document.createElement('div'), wrap = document.createElement('label'); container.className = 'manager-field'; wrap.textContent = label;
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input'); input.name = key; input.value = value || '';
    if (type !== 'textarea') input.type = type === 'date' ? 'date' : 'text';
    if (key === 'title') input.required = true;
    if (type === 'textarea') { input.rows = key === 'body' ? 18 : 6; const help = document.createElement('small'); help.textContent = 'Markdown을 사용할 수 있습니다.'; wrap.append(help); }
    wrap.append(input); container.append(wrap);
    if (type === 'image') {
      const uploadLabel = document.createElement('label'); uploadLabel.className = 'manager-upload'; uploadLabel.textContent = '이미지 업로드';
      const upload = document.createElement('input'); upload.type = 'file'; upload.accept = 'image/png,image/jpeg,image/webp,image/gif'; upload.setAttribute('aria-label',label+' 업로드');
      uploadLabel.append(upload); container.append(uploadLabel);
      const image = document.createElement('img'); image.className = 'manager-image'; image.alt = label+' 미리보기';
      const update = () => { const path = input.value.trim(); image.hidden = !path; if (path.startsWith('/images/') || path.startsWith('/uploads/')) image.src = base+'/__editor/media?path='+encodeURIComponent(path); else if (/^https:\/\//.test(path)) image.src = path; else image.hidden = true; };
      input.addEventListener('change', update); container.append(image); update();
      upload.addEventListener('change', async () => {
        const file = upload.files[0]; if (!file) return;
        if (file.size > 20*1024*1024) { showError('이미지는 20MB 이하로 선택해 주세요.'); return; }
        lock(true); showError();
        try {
          const data = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(file); });
          input.value = (await api('upload',{data})).url; update(); status('이미지를 업로드했습니다. 항목을 저장해 주세요.');
        } catch(reason) { showError(reason); } finally { lock(false); }
      });
    }
    return container;
  }
  function display(doc) {
    current = doc; $('[data-manager-delete]').hidden = Boolean(doc.new); const fields = $('[data-manager-fields]'); fields.replaceChildren();
    for (const [key,label,type] of schemas[kind]) fields.append(field(key,label,type,doc.fields[key]));
    form.elements.namedItem('draft').checked = doc.fields.draft;
    $('[data-form-heading]').textContent = doc.new ? '새 항목' : '항목 편집';
    $('[data-section-private]').hidden = catalog.settings.sections[section[kind]] !== false;
    const editor = $('[data-novel-editor]'); editor.hidden = kind !== 'books' || doc.new;
    if (!editor.hidden) editor.href = `${base}/editor/?book=${encodeURIComponent(doc.id)}`;
    form.hidden = false; $('[data-manager-preview-pane]').hidden = true; saved = JSON.stringify(values()); status();
  }
  function renderList() {
    const list = $('[data-manager-items]'); list.replaceChildren(); const items = catalog.items[kind] || [];
    $('[data-manager-count]').textContent = `${items.length}개 항목 · ${items.filter(item=>!item.draft).length}개 공개 설정`;
    for (const item of items) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'manager-item panel';
      const title = document.createElement('strong'), badge = document.createElement('span'); title.textContent = item.title; badge.textContent = item.draft ? '비공개' : catalog.settings.sections[section[kind]] === false ? '메뉴 비공개' : '공개'; badge.className = 'manager-badge';
      button.append(title,badge); button.addEventListener('click',async()=>{ if (busy || !await leave()) return; const request = ++sequence; lock(true); showError(); try { const doc=await api(`document?kind=${kind}&id=${encodeURIComponent(item.id)}`); if (request===sequence) display(doc); } catch(reason){showError(reason);} finally{lock(false);} }); list.append(button);
    }
    if (!items.length) { const empty=document.createElement('p'); empty.className='manager-empty'; empty.textContent='아직 항목이 없습니다. 새 항목으로 시작하세요.'; list.append(empty); }
  }
  function renderSettings() {
    settingsDirty=false; const target=$('[data-manager-settings]'); target.replaceChildren();
    const settingsForm=document.createElement('form'); settingsForm.className='panel manager-settings';
    const intro=document.createElement('p'); intro.textContent='메뉴 전체의 공개 여부를 관리합니다. 비공개 메뉴는 탐색 메뉴·직접 주소·검색에서 제외됩니다. 위키는 로그인한 소유자만 열 수 있습니다.'; settingsForm.append(intro);
    for (const [key,label] of Object.entries(catalog.settings.labels)) {
      const row=document.createElement('div'); row.className='manager-setting-row';
      const name=document.createElement('label'); name.textContent=label+' 메뉴 이름'; const input=document.createElement('input'); input.name='label-'+key; input.value=label; input.required=true; input.maxLength=40; name.append(input);
      const toggle=document.createElement('label'); toggle.className='manager-switch'; const check=document.createElement('input'); check.type='checkbox';check.name='public-'+key;check.checked=catalog.settings.sections[key]; toggle.append(check,document.createTextNode('외부에 공개'));row.append(name,toggle);settingsForm.append(row);
    }
    const note=document.createElement('p');note.className='manager-help';note.textContent='개별 항목은 각 편집 화면에서 비공개로 보관할 수 있습니다. 여러 공개 항목이 함께 사용하는 이미지 파일은 계속 공개됩니다. 이 설정은 이 사이트에 적용되며, YouTube 영상 자체의 공개 범위는 YouTube에서 관리합니다.';
    const save=document.createElement('button');save.type='submit';save.className='btn';save.textContent='공개 설정 저장';settingsForm.append(note,save);
    settingsForm.addEventListener('input',()=>{settingsDirty=true;$('[data-manager-count]').textContent='저장하지 않은 공개 설정';});
    settingsForm.addEventListener('submit',async(event)=>{event.preventDefault();if(busy)return;const sections={},labels={};for(const key of Object.keys(catalog.settings.sections)){sections[key]=settingsForm.elements.namedItem('public-'+key).checked;labels[key]=settingsForm.elements.namedItem('label-'+key).value;}lock(true);showError();try{catalog=await api('settings',{revision:catalog.settings.revision,sections,labels});renderSettings();$('[data-manager-count]').textContent='공개 설정을 저장했습니다.';}catch(reason){showError(reason);}finally{lock(false);}});
    target.append(settingsForm); $('[data-manager-count]').textContent='메뉴 전체와 항목별 공개 관리';
  }
  function renderTrash() {
    const target=$('[data-manager-settings]');target.replaceChildren();
    $('[data-manager-count]').textContent=`${catalog.trash.length}개 삭제한 항목`;
    const help=document.createElement('p');help.className='manager-help';help.textContent='휴지통 항목은 외부에 표시되지 않습니다. 복원하면 비공개로 돌아오므로 내용을 확인한 뒤 공개해 주세요.';target.append(help);
    for(const item of catalog.trash){
      const row=document.createElement('div');row.className='manager-trash-row panel';
      const title=document.createElement('strong');title.textContent=(names[item.kind]||'챕터')+' · '+item.title;
      const restore=document.createElement('button');restore.type='button';restore.className='btn btn--ghost';restore.textContent='비공개로 복원';
      restore.addEventListener('click',async()=>{if(busy)return;lock(true);showError();try{catalog=await api('trash',{kind:item.kind,id:item.id,revision:item.revision,action:'restore'});renderTrash();}catch(reason){showError(reason);}finally{lock(false);}});row.append(title,restore);target.append(row);
    }
    const wiki=document.createElement('a');wiki.href='https://insignia-wiki.mastercable-cloud.site/trash/';wiki.textContent='위키 문서 휴지통 ↗';wiki.className='btn btn--ghost';target.append(wiki);
  }
  async function navigate(next) {
    if (busy || !await leave()) return; kind=next; settingsDirty=false; current=null; form.hidden=true; $('[data-manager-preview-pane]').hidden=true; showError();
    root.querySelectorAll('[data-kind]').forEach(button=>button.setAttribute('aria-current',String(button.dataset.kind===kind)));
    $('[data-manager-title]').textContent=names[kind]; $('[data-manager-settings]').hidden=kind!=='settings'&&kind!=='world-wiki'&&kind!=='trash';
    $('[data-manager-new]').hidden=kind==='settings'||kind==='world-wiki'||kind==='trash'; $('[data-manager-items]').replaceChildren();
    history.replaceState(null,'',base+'/editor/manage/?section='+kind);
    if(kind==='settings'){renderSettings();return;}
    if(kind==='trash'){renderTrash();return;}
    if(kind==='world-wiki'){
      $('[data-manager-count]').textContent='같은 계정으로 관리';
      $('[data-manager-settings]').innerHTML='<section class="panel manager-settings"><p>위키 문서는 기존 위키 편집기에서 본문·이미지·공개 여부를 관리합니다. 위키 전체의 공개 여부는 공개 설정에서 변경하세요.</p><a class="btn" href="https://insignia-wiki.mastercable-cloud.site/login/?returnTo=%2Fall%2F">위키 문서 관리 ↗</a></section>';return;
    }
    renderList();
  }
  root.querySelectorAll('[data-kind]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.kind)));
  $('[data-manager-new]').addEventListener('click',async()=>{if(busy||!await leave())return;display({kind,new:true,id:null,revision:catalog.revisions[kind],fields:{draft:true}});});
  $('[data-manager-delete]').addEventListener('click',async()=>{
    if(!current||current.new||busy)return;
    if(!window.confirm(`‘${current.fields.title}’을 휴지통으로 이동할까요? 외부 공개가 중단되며 비공개로 복원할 수 있습니다.`))return;
    lock(true);showError();try{catalog=await api('trash',{kind:current.kind,id:current.id,revision:current.revision,action:'trash'});current=null;saved='';lock(false);await navigate('trash');}catch(reason){showError(reason);}finally{lock(false);}
  });
  form.addEventListener('input',()=>status());
  form.addEventListener('submit',async(event)=>{event.preventDefault();if(!current||busy)return;lock(true);showError();try{const result=await api('save',{...current,fields:values()});catalog=result;renderList();display(result.document);status('저장했습니다. 공개 설정에 따라 사이트에 반영됩니다.');}catch(reason){showError(reason);}finally{lock(false);}});
  $('[data-manager-preview]').addEventListener('click',async()=>{if(!current||busy)return;lock(true);showError();try{const fields=values(),result=await api('preview',{fields});$('[data-manager-preview-frame]').srcdoc=`<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data: https:; font-src 'self';"><style>body{font:18px/1.8 system-ui;margin:32px;color:#263340}img{max-width:100%}a{color:inherit}</style></head><body><h1>${esc(fields.title)}</h1>${result.html}</body></html>`;$('[data-manager-preview-pane]').hidden=false;}catch(reason){showError(reason);}finally{lock(false);}});
  window.addEventListener('beforeunload',event=>{if(dirty()||busy){event.preventDefault();event.returnValue='';}});
  api('catalog').then(result=>{catalog=result;const selected=new URLSearchParams(location.search).get('section');navigate(Object.hasOwn(names,selected)?selected:'settings');}).catch(showError);
})();
