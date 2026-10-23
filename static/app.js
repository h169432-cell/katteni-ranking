(() => {
  'use strict';
  const root = document.getElementById('app');
  const toastEl = document.getElementById('toast');
  const params = new URLSearchParams(location.search);
  let roomCode = (params.get('room') || '').toUpperCase().replace(/[^A-Z2-9]/g, '').slice(0, 5);
  let state = null;
  let stateVersion = -1;
  let selectedId = null;
  let editingVote = false;
  let knownRound = 0;
  let busy = false;
  let toastTimer;
  let questionDraft = '';
  let mode = roomCode ? 'room' : 'home';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function tokenFor(code) { return localStorage.getItem(`kr:host:${code}`) || localStorage.getItem(`kr:player:${code}`) || ''; }
  function isHostFor(code) { return !!localStorage.getItem(`kr:host:${code}`); }
  function shareUrl() { return `${location.origin}/?room=${encodeURIComponent(roomCode)}`; }
  function setRoom(code) {
    roomCode = code.toUpperCase(); mode = 'room'; state = null; stateVersion = -1;
    knownRound = 0; selectedId = null; editingVote = false; questionDraft = '';
    history.pushState({room: roomCode}, '', `/?room=${encodeURIComponent(roomCode)}`);
  }
  function showToast(message) {
    clearTimeout(toastTimer);
    toastEl.textContent = message;
    toastEl.classList.add('show');
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 3400);
  }
  async function request(path, method = 'GET', payload = null) {
    let res;
    try {
      res = await fetch(path, {method, headers: payload ? {'Content-Type':'application/json'} : {}, body: payload ? JSON.stringify(payload) : undefined, cache:'no-store'});
    } catch (_) { throw new Error('通信できません。ネットワークを確認してください。'); }
    let data;
    try { data = await res.json(); } catch (_) { throw new Error('サーバーから正しい応答がありません。'); }
    if (!res.ok) throw new Error(data.error || `エラー (${res.status})`);
    return data;
  }
  async function refresh(force = false) {
    if (mode !== 'room' || !roomCode) return;
    try {
      const data = await request(`/api/rooms/${roomCode}/state?token=${encodeURIComponent(tokenFor(roomCode))}`);
      const changed = data.version !== stateVersion;
      if (data.round !== knownRound) {
        knownRound = data.round; selectedId = null; editingVote = false;
      }
      state = data;
      stateVersion = data.version;
      if (!data.isHost && !data.me) mode = 'join';
      if (changed || force) render();
    } catch (err) {
      if (force || !state) renderError(err.message);
    }
  }
  function brand(dark) {
    return `<header class="nav"><a href="/" class="brand" data-action="home"><span class="brand-symbol">🏆</span><span><span class="split">みんなで決める、謎のNo.1</span>勝手にランキング選手権</span></a><button class="nav-link ${dark ? '' : 'light'}" data-action="home" type="button">トップへ</button></header>`;
  }
  function shell(body, landing = false) {
    root.innerHTML = `<div class="${landing ? 'landing' : 'page'}">${brand(landing)}${body}${landing ? '' : '<div class="footer">飲み会専用・匿名投票パーティーゲーム 🍻</div>'}</div>`;
  }
  function renderHome() {
    shell(`<main><section class="hero"><div>
      <div class="eyebrow">PARTY GAME / NO DOWNLOAD</div>
      <h1>勝手に決めて、<br><em>みんなで笑う。</em></h1>
      <p class="hero-copy">「この中で、いちばん〇〇なのは？」<br>みんなでこっそり投票して、結果をド派手に発表。<br>飲み会が一瞬で盛り上がる、匿名ランキングゲーム。</p>
      <div class="hero-cta"><button type="button" class="btn btn-yellow" data-action="create">🏆 幹事として始める <span aria-hidden="true">→</span></button><button type="button" class="btn btn-white" data-action="join-screen">📱 参加する</button></div>
      <div class="tiny-info">✓ 無料で遊べる　 ✓ アプリのインストール不要　 ✓ 2〜40人対応</div>
    </div><div class="hero-art" aria-hidden="true"><div class="art-star">✷</div><div class="sticker one">🤫 匿名投票</div><div class="fake-phone"><div class="fake-top">QUESTION 03</div><div class="fake-question">1億円当たっても<br>翌日出社しそうな人は？</div><div class="fake-row top"><span>🥇 田中さん</span><span class="pink">7票</span></div><div class="fake-row"><span>🥈 山本さん</span><span>3票</span></div><div class="fake-row"><span>🥉 鈴木さん</span><span>1票</span></div></div><div class="sticker two">😂 まさかの1位！</div></div></section>
    <section class="steps"><div class="steps-inner"><div class="step"><span class="step-number">1</span>幹事が部屋を作る</div><div class="step"><span class="step-number">2</span>全員がスマホで匿名投票</div><div class="step"><span class="step-number">3</span>結果を一斉発表！</div></div></section></main>`, true);
  }
  function renderJoin() {
    shell(`<main class="layout"><section class="panel center-panel join-panel"><div class="tiny-top">🙌</div>
      <div class="subtle-label">JOIN THE PARTY</div><h1 class="h1">ゲームに参加する</h1><p class="hint" style="margin-top:14px">幹事が表示した部屋コードと、呼ばれたい名前を入力してください。</p>
      <form id="join-form" class="form-row"><div class="input-group"><div><label class="field" for="room-input">5文字の部屋コード</label><input required autocomplete="off" autocapitalize="characters" maxlength="5" class="text-input code" id="room-input" name="code" placeholder="ABCDE" value="${esc(roomCode)}"></div>
      <div><label class="field" for="name-input">あなたの名前（14文字まで）</label><input required maxlength="14" autocomplete="nickname" class="text-input" id="name-input" name="name" placeholder="例：たなか"></div></div>
      <button class="btn btn-dark btn-wide" style="margin-top:23px" type="submit">この名前で参加する →</button></form>
      <div class="hint" style="text-align:center">投票は匿名です。誰が誰に投票したかは公開されません。</div>
    </section></main>`);
  }
  function renderError(message) {
    shell(`<main class="layout"><section class="panel center-panel" style="text-align:center"><div class="tiny-top">😵</div><h1 class="h2">部屋に接続できません</h1><p class="hint" style="margin:20px 0">${esc(message)}</p><button class="btn btn-dark btn-wide" data-action="home">トップへ戻る</button></section></main>`);
  }
  function headerRoom() {
    return `<div class="room-heading"><div><div class="room-kicker">ROOM CODE</div><div class="room-code"><strong>${esc(roomCode)}</strong><button class="pill-button" type="button" data-action="copy-code">📋 コピー</button></div></div><span class="phase ${state.status === 'voting' ? 'pink' : state.status === 'revealed' ? 'yellow' : ''}">${state.status === 'lobby' ? '🟣 参加待ち' : state.status === 'voting' ? '🗳️ 投票受付中' : '🏆 結果発表'}</span></div>`;
  }
  function chips() {
    if (!state.participants.length) return `<p class="hint">まだ参加者はいません。最初の参加を待っています。</p>`;
    return `<div class="participant-chips">${state.participants.map(p => `<span class="chip">${esc(p.name)}</span>`).join('')}</div>`;
  }
  function progress() {
    const n = state.voterCount;
    return `<div class="progress-head"><span>投票の進み具合</span><strong>${state.votedCount} / ${n} 人</strong></div><div class="progress-track"><div class="progress-fill" style="width:${n ? Math.round(state.votedCount * 100 / n) : 0}%"></div></div>`;
  }
  function sideHost() {
    return `<aside class="room-sidebar"><div class="panel"><div class="side-heading">📱 スマホで参加</div><p class="hint">このQRコードを参加者に見せてください。</p><div class="qr-wrap"><img alt="参加用QRコード" src="/api/qr?url=${encodeURIComponent(shareUrl())}"></div><p class="side-copy">または部屋コードを入力</p><div class="code-feature"><span>ROOM CODE</span><strong>${esc(roomCode)}</strong></div><div class="join-url">${esc(shareUrl())}</div><button type="button" data-action="copy-url" class="btn btn-ghost btn-wide btn-small" style="margin-top:16px">🔗 参加リンクをコピー</button></div>
      <div class="panel"><div class="side-heading">👥 参加者 <span class="badge-soft">${state.participants.length}人</span></div>${chips()}<div class="separator"></div><p class="hint">幹事の画面をテレビやプロジェクターに表示すると、結果発表が盛り上がります。</p></div>
      <div class="panel"><div class="side-heading">✏️ 質問を追加 <span class="badge-soft">追加 ${state.customQuestions.length}問</span></div>
      <p class="hint">自分で作った質問が、元の30問と一緒にランダム出題されます。ゲーム中も追加できます。</p>
      <form id="topic-form" class="topic-form"><label class="field" for="topic-input">追加したい質問</label><textarea id="topic-input" class="text-input topic-input" name="question" maxlength="120" rows="3" placeholder="例：この中で一番、宇宙人と仲良くなりそうな人は？" required>${esc(questionDraft)}</textarea>
      <button type="submit" class="btn btn-dark btn-wide btn-small">＋ この質問を追加</button></form>
      ${state.customQuestions.length ? `<div class="custom-question-heading">追加済みの質問</div><ol class="custom-question-list">${state.customQuestions.map(q => `<li>${esc(q)}</li>`).join('')}</ol>` : ''}</div></aside>`;
  }
  function hostContent() {
    let stage;
    if (state.status === 'lobby') {
      stage = `<div class="stage"><span class="phase">👋 WELCOME!</span><h1 class="stage-title">みんな集まったら、<br>ランキング開始！</h1><p class="stage-description">右のQRコードから参加してもらおう。<br>2人以上集まればスタートできます。</p><div class="stage-actions"><button type="button" class="btn btn-dark" data-action="start" ${state.participants.length < 2 ? 'disabled' : ''}>最初のお題へ →</button></div></div>`;
    } else if (state.status === 'voting') {
      stage = `<div class="stage"><span class="subtle-label">QUESTION ${String(state.round).padStart(2, '0')}</span><span class="phase pink">🤫 こっそり投票中</span><h1 class="stage-title">${esc(state.topic.question)}</h1><p class="stage-description">スマホで1人を選んで投票してください。</p><div style="width:100%">${progress()}</div><div class="stage-actions"><button type="button" class="btn btn-pink" data-action="reveal" ${!state.votedCount ? 'disabled' : ''}>🎉 結果を発表する →</button></div>${state.votedCount === state.voterCount ? '<div class="callout">🎊 全員の投票が完了！発表の準備OK！</div>' : ''}</div>`;
    } else {
      stage = `<div>${resultHTML()}<div class="stage-actions"><button type="button" class="btn btn-dark" data-action="next">次のお題へ →</button></div></div>`;
    }
    return `<main class="layout"><div class="two-col"><section class="panel">${headerRoom()}${stage}</section>${sideHost()}</div></main>`;
  }
  function playerLobby() {
    return `<div class="stage stage-center"><div class="success-emoji">🙌</div><span class="phase">参加できました！</span><h1 class="stage-title">${esc(state.me.name)}さん、<br>いらっしゃい！</h1><p class="stage-description">お題が始まるまで、そのままお待ちください。<br>参加者は現在 ${state.participants.length}人！</p><div class="participant-chips" style="justify-content:center">${state.participants.map(p => `<span class="chip">${esc(p.name)}</span>`).join('')}</div><div class="callout">⏳ 幹事がスタートしたら自動で画面が切り替わります。</div></div>`;
  }
  function playerVoting() {
    const eligible = state.eligible;
    if (!eligible) {
      return `<div class="stage stage-center"><div class="success-emoji">⏭️</div><h1 class="stage-title">次のお題から参加！</h1><p class="stage-description">このお題はすでに始まっていました。<br>次のラウンドでは投票できます。</p></div>`;
    }
    if (state.myVote && !editingVote) {
      return `<div class="stage stage-center"><div class="success-emoji">✅</div><span class="phase">投票完了！</span><h1 class="success-title" style="margin:20px 0 13px">投票できました！</h1><p class="stage-description">誰に投票したかはヒミツ。<br>結果発表を楽しみに待とう！</p><p class="hint" style="margin-top:25px">現在 ${state.votedCount} / ${state.voterCount} 人が投票済み</p><button class="btn btn-ghost btn-small" data-action="change-vote" style="margin-top:18px">投票を変更する</button></div>`;
    }
    const eligiblePeople = state.participants.filter(p => state.candidateIds.includes(p.id));
    const options = eligiblePeople.map(p => {
      const isMe = p.id === state.me.id;
      const selected = p.id === selectedId;
      return `<button type="button" class="vote-option ${selected ? 'selected' : ''}" data-action="pick" data-id="${esc(p.id)}" aria-pressed="${selected}" ${isMe ? 'disabled' : ''}><span class="vote-icon">${selected ? '💗' : isMe ? '🙋' : '👤'}</span>${esc(p.name)}${isMe ? '<span class="hint">自分です</span>' : ''}</button>`;
    }).join('');
    return `<div><span class="subtle-label">QUESTION ${String(state.round).padStart(2, '0')}</span><h1 class="h1" style="margin-top:4px;line-height:1.48">${esc(state.topic.question)}</h1><div class="vote-grid">${options}</div><div class="vote-tip">🤫 投票は匿名／自分以外に1票</div><button type="button" class="btn btn-pink btn-wide" data-action="vote" style="margin-top:20px" ${!selectedId ? 'disabled' : ''}>${state.myVote ? '投票を変更する' : 'この人に投票する'} →</button></div>`;
  }
  function resultHTML() {
    const results = state.results || [];
    const winners = results.filter(p => p.rank === 1 && p.votes > 0);
    const winnerName = winners.map(p => p.name).join(' ＆ ');
    const maxVotes = Math.max(1, ...results.map(p => p.votes));
    const rows = results.map(p => `<div class="rank-row ${p.rank === 1 ? 'first' : ''}"><div class="rank-num">${p.rank === 1 ? '🥇' : p.rank === 2 ? '🥈' : p.rank === 3 ? '🥉' : p.rank + '位'}</div><div class="rank-main"><div class="rank-person">${esc(p.name)}</div><div class="rank-track"><div class="rank-bar" style="width:${Math.round(p.votes * 100 / maxVotes)}%"></div></div></div><div class="rank-votes">${p.votes}<span class="hint">票</span></div></div>`).join('');
    return `<div><div class="result-hero"><span class="result-medal">🏆</span><div class="result-label">第${state.round}問・勝手にNo.1 決定！</div><h1 class="result-winner">${esc(winnerName)}</h1><div class="result-award">👑 ${esc(state.topic.award)}</div><p class="hint" style="margin-top:18px">${state.votedCount}人の投票で決定！${winners.length > 1 ? ' なんと同率1位！' : ''}</p></div><div class="h3">📊 投票結果</div><div class="rank-list">${rows}</div></div>`;
  }
  function participantContent() {
    let content = state.status === 'lobby' ? playerLobby() : state.status === 'voting' ? playerVoting() : `${resultHTML()}<p class="hint" style="text-align:center;margin-top:25px">次のお題を待っています <span class="waiting-dots">●●●</span></p>`;
    return `<main class="layout"><section class="panel center-panel" style="margin-top:18px">${headerRoom()}${content}</section></main>`;
  }
  function render() {
    if (mode === 'home') { renderHome(); return; }
    if (mode === 'join' || !roomCode || (state && !state.isHost && !state.me)) { renderJoin(); return; }
    if (!state) { root.innerHTML = '<div class="boot"><div class="loader"></div>部屋を読み込み中…</div>'; return; }
    const active = document.activeElement;
    const focusedQuestion = active && active.id === 'topic-input';
    const selection = focusedQuestion ? [active.selectionStart, active.selectionEnd] : null;
    shell(state.isHost ? hostContent() : participantContent());
    if (focusedQuestion && state.isHost) {
      const input = document.getElementById('topic-input');
      input.focus({preventScroll: true});
      input.setSelectionRange(selection[0], selection[1]);
    }
  }
  document.addEventListener('input', event => {
    if (event.target.id === 'topic-input') questionDraft = event.target.value;
  });
  async function runTask(callback) {
    if (busy) return;
    busy = true;
    try { await callback(); } catch (err) { showToast(err.message); }
    finally { busy = false; }
  }
  async function doPost(action, data) {
    return request(`/api/rooms/${roomCode}/${action}`, 'POST', data);
  }
  document.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-action]');
    if (!btn) return;
    event.preventDefault();
    const action = btn.dataset.action;
    if (action === 'home') {
      history.pushState({}, '', '/'); mode = 'home'; state = null; roomCode = ''; render(); return;
    }
    if (action === 'join-screen') { mode = 'join'; render(); return; }
    if (action === 'copy-code' || action === 'copy-url') {
      const content = action === 'copy-code' ? roomCode : shareUrl();
      try { await navigator.clipboard.writeText(content); showToast('コピーしました！'); }
      catch (_) { showToast(`コピーできませんでした：${content}`); }
      return;
    }
    if (action === 'pick') { selectedId = btn.dataset.id; render(); return; }
    if (action === 'change-vote') { editingVote = true; selectedId = state.myVote; render(); return; }
    if (action === 'create') {
      await runTask(async () => {
        btn.disabled = true; btn.textContent = '部屋を作成中…';
        const data = await request('/api/rooms', 'POST', {});
        localStorage.setItem(`kr:host:${data.code}`, data.hostToken);
        setRoom(data.code); await refresh(true);
      }); return;
    }
    if (action === 'start' || action === 'reveal' || action === 'next') {
      await runTask(async () => {
        await doPost(action, {hostToken: localStorage.getItem(`kr:host:${roomCode}`)});
        await refresh(true);
        if (action === 'reveal') window.scrollTo({top:0,behavior:'smooth'});
      }); return;
    }
    if (action === 'vote') {
      if (!selectedId) return;
      await runTask(async () => {
        await doPost('vote', {participantToken: localStorage.getItem(`kr:player:${roomCode}`),candidateId:selectedId});
        editingVote = false; await refresh(true); showToast('投票を受け付けました！ 🎉');
      });
    }
  });
  document.addEventListener('submit', async (event) => {
    if (event.target.id === 'topic-form') {
      event.preventDefault();
      const question = questionDraft.trim();
      await runTask(async () => {
        await doPost('add-topic', {hostToken: localStorage.getItem(`kr:host:${roomCode}`), question});
        questionDraft = '';
        await refresh(true);
        showToast('質問を追加しました！');
      });
      return;
    }
    if (event.target.id !== 'join-form') return;
    event.preventDefault();
    const codeInput = event.target.elements.code;
    const nameInput = event.target.elements.name;
    const code = codeInput.value.trim().toUpperCase().replace(/[^A-Z2-9]/g, '');
    const name = nameInput.value.trim();
    if (code.length !== 5) { showToast('部屋コードは5文字です。'); return; }
    if (!name || name.length > 14) { showToast('名前は1〜14文字で入力してください。'); return; }
    await runTask(async () => {
      const result = await request(`/api/rooms/${code}/join`, 'POST', {name, participantToken: localStorage.getItem(`kr:player:${code}`) || ''});
      localStorage.setItem(`kr:player:${code}`, result.participantToken);
      if (roomCode !== code || mode !== 'room') setRoom(code);
      else { mode = 'room'; stateVersion = -1; }
      await refresh(true); showToast('参加できました！');
    });
  });
  window.addEventListener('popstate', () => {
    const query = new URLSearchParams(location.search);
    roomCode = (query.get('room') || '').toUpperCase();
    mode = roomCode ? 'room' : 'home'; state = null; stateVersion = -1;
    render(); if (roomCode) refresh(true);
  });
  render();
  if (roomCode) refresh(true);
  setInterval(() => { if (mode === 'room' && !busy) refresh(); }, 1500);
})();
