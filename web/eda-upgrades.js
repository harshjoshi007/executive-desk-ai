/* Executive Desk AI — additive section upgrades, 2026-11-14.
   Loaded AFTER the existing application. Replaces only targeted page renderers,
   uses the same global `data`, `ui`, `persist`, `logActivity`, and existing auth/cloud.
   All new delegated events have an eda- prefix, captured before legacy handlers. */
(() => {
'use strict';
const H = s => esc(s==null?'':s);
const now = () => new Date().toISOString();
const D = () => indiaDate();
const E = (name='chevron') => icon(name);
const field = (label, name, value='', type='text', attrs='')=>`<label class="eda-field"><span>${H(label)}</span><input class="field" name="${name}" type="${type}" value="${H(value)}" ${attrs}></label>`;
const textarea = (label,name,value='',rows=3,attrs='')=>`<label class="eda-field"><span>${H(label)}</span><textarea class="field" name="${name}" rows="${rows}" ${attrs}>${H(value)}</textarea></label>`;
const pick = (label,name,values,value='')=>`<label class="eda-field"><span>${H(label)}</span><select class="field" name="${name}">${values.map(v=>`<option value="${H(v)}" ${v===value?'selected':''}>${H(v)}</option>`).join('')}</select></label>`;
const B = (a,label,id='',cl='subtle',extra='')=>`<button type="button" class="btn ${cl}" data-eda="${a}" data-id="${H(id)}" ${extra}>${label}</button>`;
const More = (items)=>`<details class="eda-dots"><summary aria-label="More actions" title="Actions">⋯</summary><div class="eda-menu">${items.map(([a,label,id])=>`<button type="button" data-eda="${a}" data-id="${H(id)}">${H(label)}</button>`).join('')}</div></details>`;
const head = (title,subtitle,action='')=>`<header class="eda-pagehead"><div><span class="eyebrow">EXECUTIVE DESK AI</span><h1>${H(title)}</h1><p>${H(subtitle)}</p></div><div class="eda-head-actions">${action}</div></header>`;
const section=(title,body,aside='')=>`<section class="eda-panel"><header class="eda-panelhead"><h2>${title}</h2>${aside}</header>${body}</section>`;
const empty=(title,body='')=>`<div class="eda-empty"><span class="eda-empty-icon">${E('folder')}</span><b>${H(title)}</b><p>${H(body)}</p></div>`;
const fmtDay=d=>{if(!d)return 'Not scheduled';try{return new Date(String(d).slice(0,10)+'T12:00:00Z').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})}catch{return String(d)}};
const fmtStamp=d=>{if(!d)return '';const x=new Date(d);return Number.isNaN(+x)?fmtDay(d):x.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit'})};
const byId=(arr,id)=>arr.find(x=>String(x.id)===String(id));
const inList=(s,q)=>(String(s||'').toLowerCase().includes(String(q||'').toLowerCase()));
const trSet=()=>data.trips??=[];
function preserve(type,r,action,before=null,detail=''){logActivity(type,r.id,r.title||r.meetingTitle||r.name||r.subject||String(r.body||'').slice(0,60),action,before,r,detail);persist()}
function removeRecord(type,id){v11DeleteRecord(type,id)}
function setStatus(type,arr,id,to){const r=byId(arr,id);if(!r)return;const old=cloneRecord(r);r.status=to;r.updatedAt=now();if(to==='Completed')r.completedAt=now();else delete r.completedAt;preserve(type,r,to==='Completed'?'Completed':to==='Cancelled'?'Cancelled':'Reopened',old)}
function goHist(section='All',view='Activity'){ui.historyView=view;ui.edaHistoryKind=section;nav('More','activity')}
const uiState={noteFilter:'All',noteEditor:false,noteLimit:25,momFilter:'All',momLimit:25,momOpen:null,tripFilter:'Upcoming',tripSelect:'',tripEditor:false,tripEditId:'',tripTab:'overview',histQuery:'',histStatus:'All',histFrom:'',histTo:'',histLimit:40,googleSyncLog:[],mailFolder:'INBOX',mailQuery:'',mailRows:[],mailCursor:null,mailHasMore:false,mailLoading:false,mailError:'',mailSelected:null,mailDetail:null,mailCompose:false,mailDraft:null,mailBusy:false};
const refresh = ()=>render();
function dateOnlyParam(value){return /^\d{4}-\d{2}-\d{2}$/.test(String(value||''))?value:''}
function listCount(n){return `${n} record${n===1?'':'s'}`}
function noteIsArchived(n){return !!n.archivedAt}

/* ======================== MY NOTES ======================== */
quickNotesPage = function(){
 const filter=uiState.noteFilter,q=String(ui.noteQuery||'').trim().toLowerCase();
 const all=(data.quickNotes||[]).filter(n=>!n.demo);const archived=all.filter(noteIsArchived);
 let items=all.filter(n=>filter==='Archived'?noteIsArchived(n):!noteIsArchived(n));
 if(filter==='Pinned')items=items.filter(n=>n.pinned);
 if(filter==='Reminders')items=items.filter(n=>n.reminderEnabled&&(n.reminderDate||n.remindOn));
 items=items.filter(n=>inList([n.title,n.body,n.category].join(' '),q));
 items.sort((a,b)=>(filter==='All'?(Number(!!b.pinned)-Number(!!a.pinned)):0)||String(b.updatedAt||b.createdAt).localeCompare(String(a.updatedAt||a.createdAt)));
 const current=byId(all,ui.editQuickNoteId)||null,showEditor=uiState.noteEditor||!!current;
 const editor=`<form id="eda-note-form" class="eda-form">${field('Title (optional)','title',current?.title||'','text','maxlength="300"')}${pick('Category (optional)','category',['','Work','Personal','Meeting Notes','Travel','Ideas','Planning'],current?.category||'')}${textarea('Write your note *','body',current?.body||'',7,'required')}
 <div class="eda-grid-2">${field('Show in Upcoming (optional)','remindOn',current?.remindOn||'','date')}${field('Reminder date (optional)','reminderDate',current?.reminderDate||(current?.reminderEnabled?current?.remindOn:'')||'','date')}${field('Reminder time (optional)','reminderTime',current?.reminderTime||'','time')}</div>
 <div class="eda-checkrow"><label><input type="checkbox" name="reminderEnabled" ${current?.reminderEnabled?'checked':''}> Send notification on the reminder date</label><label><input type="checkbox" name="pinned" ${current?.pinned?'checked':''}> Pin note</label></div>
 <div class="eda-form-actions"><button type="submit" class="btn">${E('check')} ${current?'Save changes':'Save Note'}</button>${B('note-cancel','Cancel','','subtle')}</div></form>`;
 const card=n=>`<article class="eda-record"><div class="eda-record-main"><div class="eda-record-meta">${n.pinned?'<span class="eda-chip">📌 Pinned</span>':''}${n.category?`<span class="eda-chip">${H(n.category)}</span>`:''}${n.remindOn?`<span class="eda-chip">Upcoming ${H(fmtDay(n.remindOn))}</span>`:''}${n.reminderEnabled&&(n.reminderDate||n.remindOn)?`<span class="eda-chip">${E('bell')} Reminder ${H(fmtDay(n.reminderDate||n.remindOn))}${n.reminderTime?' · '+H(n.reminderTime):''}</span>`:''}</div><button class="eda-record-title" data-eda="note-edit" data-id="${H(n.id)}">${H(n.title||String(n.body).split('\n')[0].slice(0,80))}</button><p class="eda-clamp">${H(n.body)}</p><small>${H(fmtStamp(n.updatedAt||n.createdAt))}</small></div>${More([['note-edit','Edit',n.id],['note-pin',n.pinned?'Unpin':'Pin',n.id],['note-reminder','Set / remove reminder',n.id],['note-upcoming','Show / remove from Upcoming',n.id],['note-archive',n.archivedAt?'Unarchive':'Archive',n.id],['note-trash','Move to Trash',n.id]])}</article>`;
 return `<div class="eda-upgrade">${head('My Notes','A simple, searchable scribble pad for everything worth remembering.',B('note-new','+ Add Note','',''))}<div class="eda-two"><div class="eda-desktop-editor">${section(current?'Edit Note':'Add Note',editor)}</div><div>${section('Saved Notes',`<div class="eda-toolbar"><div class="eda-tabs">${['All','Pinned','Recent','Reminders','Archived'].map(f=>`<button class="${filter===f?'active':''}" data-eda="note-filter" data-id="${f}">${f}</button>`).join('')}</div><input class="field eda-search" id="eda-note-search" aria-label="Search notes" placeholder="Search all notes…" value="${H(ui.noteQuery||'')}"></div><div class="eda-list">${items.slice(0,uiState.noteLimit).map(card).join('')||empty('No matching notes',filter==='Archived'?'Archived notes appear here.':'Save a note to see it here.')}</div>${items.length>uiState.noteLimit?B('note-more','Load more') :''}`,`<span class="eda-muted">${items.length} shown · ${archived.length} archived</span>`)}</div></div><div class="eda-mobile-editor ${showEditor?'is-open':''}">${section(current?'Edit Note':'Add Note',editor)}</div></div>`;
};

/* ======================= MINUTES OF MEETING ======================= */
function actionRows(m){const rows=Array.isArray(m?.actionItems)?m.actionItems:(m?.actions||[]).map((x,i)=>({id:'legacy-'+i,title:typeof x==='string'?x:String(x?.title||''),owner:m.owner||'',dueDate:m.deadline||'',priority:'Normal',status:'Pending',taskId:''}));return rows.map(r=>{const linked=r.taskId?byId(data.tasks||[],r.taskId):null;return linked?{...r,status:linked.status||r.status,owner:linked.person??r.owner}:r});}
function momActionRow(a={}){return `<div class="eda-action-row" data-eda-action-row data-id="${H(a.id||newId())}">${field('Action','actionTitle',a.title||'','text','placeholder="What needs doing?"')}${field('Owner','actionOwner',a.owner||'','text')}${field('Due date','actionDue',a.dueDate||'','date')}${pick('Priority','actionPriority',['Normal','High','Low'],a.priority||'Normal')}${B('mom-remove-row','Remove','','subtle')}${a.taskId?`<small>Linked Task Manager task · ${H(a.status||'Pending')}</small>`:''}<input type="hidden" name="actionTaskId" value="${H(a.taskId||'')}"></div>`}
minutesPage = function(){const current=byId(data.meetingNotes||[],ui.editMomId);const draft=current?.draft||false;
 const q=String(ui.momSearch||'').toLowerCase();let all=(data.meetingNotes||[]).filter(m=>!m.demo);
 const filt=uiState.momFilter;if(filt==='Drafts')all=all.filter(x=>x.draft);else if(filt==='Final')all=all.filter(x=>!x.draft);else if(filt==='Archived')all=all.filter(x=>x.archivedAt);else all=all.filter(x=>!x.archivedAt);
 all=all.filter(m=>inList([m.meetingTitle,m.attendees,m.notes,m.decisions,(m.actions||[]).join(' '),(m.actionItems||[]).map(x=>x.title).join(' ')].join(' '),q)).sort((a,b)=>String(b.updatedAt||b.date||'').localeCompare(String(a.updatedAt||a.date||'')));
 const rows=actionRows(current);
 const form=`<form class="eda-form" id="eda-mom-form"><div class="eda-grid-2">${field('Meeting / Discussion Title *','title',current?.meetingTitle||'','text','required maxlength="300"')}${field('Discussion Date *','day',current?.discussionDate||String(current?.date||'').slice(0,10)||D(),'date','required')}${field('Time (optional)','time',current?.discussionTime||'','time')}${field('Attendees (optional)','attendees',current?.attendees||'','text')}</div>${textarea('Discussion / Exact Notes','notes',current?.notes||'',6)}${textarea('Decisions / Outcomes','decisions',current?.decisions||'',3)}<div class="eda-panelhead"><h3>Action Points</h3>${B('mom-add-row','+ Add Action Point')}</div><div id="eda-mom-rows">${rows.map(momActionRow).join('')}</div><label class="eda-checkrow"><input type="checkbox" name="createTasks"> Create linked Task Manager tasks for action points (optional)</label><div class="eda-form-actions"><button class="btn" type="submit" name="finish" value="final">${E('check')} ${current&&!draft?'Update MOM':'Save MOM'}</button><button class="btn subtle" type="submit" name="finish" value="draft">Save as Draft</button>${current?B('mom-export','Download PDF',current.id):''}${current?B('mom-reset','Cancel Edit'):''}</div></form>`;
 const row=m=>`<article class="eda-record"><div class="eda-record-main"><div class="eda-record-meta"><span class="eda-chip">${m.draft?'Draft':'Final'}</span><small>${H(fmtDay(m.discussionDate||m.date))}</small><small>${actionRows(m).length} action point(s)</small></div><button class="eda-record-title" data-eda="mom-open" data-id="${H(m.id)}">${H(m.meetingTitle)}</button><p class="eda-clamp">${H(m.notes||'No discussion entered')}</p></div>${More([['mom-open','View full MOM',m.id],['mom-edit','Edit',m.id],['mom-export','Download PDF',m.id],['mom-task-review','Linked Tasks',m.id],['mom-archive',m.archivedAt?'Unarchive':'Archive',m.id],['mom-trash','Move to Trash',m.id]])}</article>`;
 return `<div class="eda-upgrade">${head('Minutes of Meeting (MOM)','Record discussions, decisions and action points independently of Calendar.')}
 <div class="eda-mobile-tabs">${B('mom-mobile-tab','Write MOM','write',uiState.momOpen!=='list'?'':'subtle')}${B('mom-mobile-tab','Previous Minutes','list',uiState.momOpen==='list'?'':'subtle')}</div>
 <div class="eda-two"><div class="eda-mom-editor ${uiState.momOpen==='list'?'eda-mobile-hidden':''}">${section(current?'Edit Meeting Minutes':'Write Meeting Minutes',form)}</div><div class="eda-mom-list ${uiState.momOpen==='list'?'':'eda-mobile-hidden'}">${section('Previous Minutes',`<div class="eda-toolbar"><div class="eda-tabs">${['All','Drafts','Final','Archived'].map(f=>`<button data-eda="mom-filter" data-id="${f}" class="${filt===f?'active':''}">${f}</button>`).join('')}</div><input id="eda-mom-search" class="field eda-search" placeholder="Search discussions, attendees…" value="${H(ui.momSearch||'')}"></div><div class="eda-list">${all.slice(0,uiState.momLimit).map(row).join('')||empty('No meeting minutes saved yet','Record a discussion to start your MOM history.')}</div>${all.length>uiState.momLimit?B('mom-more','Load more'):''}`,`<span class="eda-muted">${listCount(all.length)}</span>`)}</div></div></div>`;
};

/* ============================ TRAVEL DESK ============================ */
const TRIP_CHECKS=['Flight / train booked','Hotel confirmed','Ground transportation','Meeting agenda ready','Identification & documents','Emergency contacts shared'];
function checklistFor(t){return Array.isArray(t.checklist)&&t.checklist.length?t.checklist:TRIP_CHECKS.map((title,i)=>({id:'basic-'+i,title,done:false}));}
function travelRow(kind,r={}){return `<div class="eda-travel-row" data-trip-row="${kind}" data-id="${H(r.id||newId())}">${kind==='leg'?`<div class="eda-grid-2">${pick('Transport','transportType',['Flight','Train','Car','Other'],r.transportType||'Flight')}${field('Operator / Airline','operator',r.operator||'')}${field('Departure place','from',r.from||'')}${field('Arrival place','to',r.to||'')}${field('Departure date & time','departAt',r.departAt||'','datetime-local')}${field('Arrival date & time','arriveAt',r.arriveAt||'','datetime-local')}${field('Flight / Train No.','number',r.number||'')}${field('Booking Reference / PNR','bookingRef',r.bookingRef||'')}${pick('Booking Status','bookingStatus',['Not Booked','Pending','Confirmed','Cancelled'],r.bookingStatus||'Not Booked')}</div>`:kind==='hotel'?`<div class="eda-grid-2">${field('Hotel name','name',r.name||'')}${field('Address','address',r.address||'')}${field('Check in','checkIn',r.checkIn||'','date')}${field('Check out','checkOut',r.checkOut||'','date')}${field('Booking reference','bookingRef',r.bookingRef||'')}${pick('Status','bookingStatus',['Not Booked','Pending','Confirmed','Cancelled'],r.bookingStatus||'Not Booked')}</div>`:`<div class="eda-grid-2">${field('Transport / Driver','provider',r.provider||'')}${field('Pickup','pickup',r.pickup||'')}${field('Drop','drop',r.drop||'')}${field('Date / time','when',r.when||'','datetime-local')}${field('Contact','contact',r.contact||'')}${pick('Status','bookingStatus',['Not Booked','Pending','Confirmed','Cancelled'],r.bookingStatus||'Not Booked')}</div>`}${B('trip-remove-row','Remove','','subtle')}</div>`;}
function selectedTrip(){return byId(data.trips||[],uiState.tripSelect)||(data.trips||[]).find(t=>!['Completed','Cancelled'].includes(t.status))||null;}
function tripForm(t){const edit=!!t;return `<form id="eda-trip-form" class="eda-form">${field('Trip name / Purpose *','title',t?.title||'','text','required')}
<div class="eda-grid-2">${field('Traveller(s)','travellers',t?.travellers||'')}${field('Destination city *','city',t?.city||'','text','required')}${field('Country','country',t?.country||'India')}${pick('Trip type','tripType',['Domestic','International'],t?.tripType||'Domestic')}${field('Departure date *','start',t?.start||'','date','required')}${field('Return date *','end',t?.end||'','date','required')}${pick('Trip status','status',['Planning','Awaiting Confirmation','Confirmed','In Progress','Completed','Cancelled'],t?.status||'Planning')}</div>
${textarea('Agenda / Notes','notes',t?.notes||'',3)}<details class="eda-form-expand"><summary>Flights / Trains / Travel Legs</summary><div id="eda-trip-legs">${(t?.legs||[]).map(x=>travelRow('leg',x)).join('')}</div>${B('trip-add-row','+ Add transport booking','leg')}</details>
<details class="eda-form-expand"><summary>Hotels / Accommodation</summary><div id="eda-trip-hotels">${(t?.hotels||[]).map(x=>travelRow('hotel',x)).join('')}</div>${B('trip-add-row','+ Add hotel','hotel')}</details>
<details class="eda-form-expand"><summary>Pickup / Local Transport</summary><div id="eda-trip-ground">${(t?.groundTransport||[]).map(x=>travelRow('ground',x)).join('')}</div>${B('trip-add-row','+ Add transport arrangement','ground')}</details>
${textarea('Meeting agenda (optional, no Calendar event created)','agenda',t?.agenda||'',2)}${field('Reminder date (optional)','remindOn',t?.remindOn||'','date')}
<div class="eda-form-actions"><button class="btn" type="submit">${edit?'Save Trip Changes':'Save Trip'}</button>${B('trip-editor-close','Cancel','','subtle')}</div></form>`}
travelPage = function(){const trips=(data.trips||[]).filter(x=>!x.demo);const today=D();const future=trips.filter(t=>t.end>=today&&!['Completed','Cancelled'].includes(t.status));const needs=t=>t.status==='Awaiting Confirmation'||(t.status==='Planning')||[...(t.legs||[]),...(t.hotels||[]),...(t.groundTransport||[])].some(b=>b.bookingStatus&&b.bookingStatus!=='Confirmed'&&b.bookingStatus!=='Cancelled');
 let shown=trips.filter(t=>uiState.tripFilter==='All'||uiState.tripFilter==='Upcoming'&&future.includes(t)||uiState.tripFilter==='Need Action'&&needs(t)&&!['Completed','Cancelled'].includes(t.status)||uiState.tripFilter===t.status).sort((a,b)=>String(a.start).localeCompare(String(b.start)));
 const chosen=selectedTrip(),editing=byId(trips,uiState.tripEditId)||null;
 const counter=(number,label,filter)=>`<button class="eda-counter" type="button" data-eda="trip-filter" data-id="${H(filter)}"><strong>${number}</strong><span>${H(label)}</span></button>`;
 const card=t=>`<article class="eda-record ${chosen?.id===t.id?'selected':''}"><div class="eda-record-main"><span class="eda-record-meta"><span class="eda-chip">${H(t.status||'Planning')}</span><span>${H(fmtDay(t.start))} – ${H(fmtDay(t.end))}</span></span><button class="eda-record-title" data-eda="trip-select" data-id="${H(t.id)}">${H(t.title)}</button><p>${E('plane')} ${H(t.city||'Destination not provided')}${t.country?' · '+H(t.country):''}</p><small>Transport: ${H((t.legs||[]).some(x=>x.bookingStatus==='Confirmed')?'Booked':t.flight?'Details entered':'Pending')} · Hotel: ${H((t.hotels||[]).some(x=>x.bookingStatus==='Confirmed')?'Confirmed':t.hotel?'Details entered':'Pending')}</small></div>${More([['trip-select','Open Itinerary',t.id],['trip-edit','Edit Trip',t.id],['trip-status','Update Status',t.id],['trip-reminder','Set Reminder',t.id],['trip-export','Download Itinerary PDF',t.id],['trip-complete','Mark Completed',t.id],['trip-cancel','Cancel Trip',t.id],['trip-trash','Move to Trash',t.id]])}</article>`;
 const checklist=chosen?checklistFor(chosen).map(c=>`<label class="eda-checklist"><input type="checkbox" data-eda="trip-check" data-trip-id="${H(chosen.id)}" data-id="${H(c.id)}" ${c.done?'checked':''}><span>${H(c.title)}</span></label>`).join(''):TRIP_CHECKS.map(x=>`<label class="eda-checklist disabled"><input type="checkbox" disabled><span>${H(x)}</span></label>`).join('');
 const book=chosen?`<div class="eda-trip-summary"><b>${H(chosen.title)}</b><span>${H(chosen.travellers||'Traveller not set')} · ${H(fmtDay(chosen.start))}–${H(fmtDay(chosen.end))}</span><p>${H(chosen.notes||'')}</p>${[...(chosen.legs||[])].map(x=>`<p>✈ ${H(x.from)} → ${H(x.to)} · ${H(x.operator)} · ${H(x.bookingStatus)}</p>`).join('')}${(chosen.hotels||[]).map(x=>`<p>⌂ ${H(x.name)} · ${H(x.bookingStatus)}</p>`).join('')}${B('trip-export','Download itinerary PDF',chosen.id)}</div>`:'';
 const right=section('Trip Checklist',`<small class="eda-muted">${chosen?'For: '+H(chosen.title):'Template — select a trip to begin tracking'}</small><div class="eda-list">${checklist}</div>${chosen?B('trip-add-check','+ Checklist item',chosen.id):''}`)+ (chosen?section('Selected Trip Itinerary',book):'');
 const layout=`<div class="eda-three-counters">${counter(future.length,'Trips Planned','Upcoming')}${counter(future.filter(x=>x.status==='Confirmed').length,'Confirmed Trips','Confirmed')}${counter(future.filter(needs).length,'Need Confirmation','Need Action')}</div><div class="eda-two">${section('Upcoming Itineraries',`<div class="eda-tabs">${['Upcoming','All','Need Action','Confirmed','Planning','Completed','Cancelled'].map(x=>`<button data-eda="trip-filter" data-id="${x}" class="${uiState.tripFilter===x?'active':''}">${x}</button>`).join('')}</div><div class="eda-list">${shown.map(card).join('')||empty('No upcoming itineraries yet','Create your first trip to organise bookings, logistics and reminders.')}</div>${!trips.length?B('trip-new','+ Create First Itinerary','',''):''}`,`<span class="eda-muted">${listCount(shown.length)}</span>`)}<div>${right}</div></div>`;
 return `<div class="eda-upgrade">${head('Travel Desk','Plan trips, bookings, itineraries and checklists without losing track.',B('trip-new','+ New Trip','','')+B('history-travel','History & Trips'))}${uiState.tripEditor?section(editing?'Edit Trip':'New Trip',tripForm(editing)):layout}</div>`;
};

/* ========================== HISTORY & RECOVERY =========================== */
function histRows(){return (data.activities||[]).filter(x=>x&&x.at).filter(x=>!/^Sync(ed|ing)? from/i.test(String(x.action||''))&& !/^(Sync|Synced)( |$)/i.test(String(x.title||'')));}
function histKinds(){return ['All',...new Set([...histRows().map(x=>x.recordType),...allRecords().map(x=>x.type),...(data.trash||[]).map(x=>x.recordType)].filter(Boolean))].sort((a,b)=>a==='All'?-1:b==='All'?1:a.localeCompare(b));}
function histDate(x){return String(x||'').slice(0,10)}
function histMatchDate(x){const date=histDate(x),from=uiState.histFrom,to=uiState.histTo;return (!from||date>=from)&&(!to||date<=to)}
function histMenu(a){return More([['hist-open','Open Original',a.id],['hist-changes','View Changes',a.id],['hist-reopen','Reopen if applicable',a.id]]);}
v11HistoryPage = function(){const view=ui.historyView||'Activity',kind=uiState.histKind||ui.edaHistoryKind||'All',q=uiState.histQuery.trim().toLowerCase(),status=uiState.histStatus;
 let rows=[];
 if(view==='Activity')rows=histRows().filter(a=>(kind==='All'||a.recordType===kind)&&inList([a.title,a.recordType,a.action,a.detail].join(' '),q)&&(status==='All'||inList(a.action,status))&&histMatchDate(a.at)).sort((a,b)=>String(b.at).localeCompare(String(a.at)));
 else if(view==='Trash')rows=(data.trash||[]).filter(x=>(kind==='All'||x.recordType===kind)&&inList([x.title,x.recordType].join(' '),q)&&histMatchDate(x.deletedAt)).sort((a,b)=>String(b.deletedAt).localeCompare(String(a.deletedAt)));
 else rows=allRecords().filter(x=>x.type!=='Activity').filter(x=>(kind==='All'||x.type===kind)&&inList([x.title,x.body,x.source].join(' '),q)&&histMatchDate(x.date)).sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
 const filter=`<div class="eda-filters">${field('Search records','query',uiState.histQuery,'search','id="eda-history-query" placeholder="Title, person, action…"')}${field('From','from',uiState.histFrom,'date')}${field('To','to',uiState.histTo,'date')}${pick('Section','kind',histKinds(),kind)}${pick('Status / Action','status',['All','Created','Edited','Completed','Rescheduled','Reopened','Cancelled','Restored','Trash'],status)}${B('hist-clear','Clear Filters')}</div>`;
 const row=a=>view==='Activity'?`<article class="eda-record"><div class="eda-record-main"><div class="eda-record-meta"><span class="eda-chip">${H(a.action)}</span><span>${H(a.recordType)}</span><span>${H(fmtStamp(a.at))}</span></div><button class="eda-record-title" data-eda="hist-open" data-id="${H(a.id)}">${H(a.title)}</button>${a.detail?`<p>${H(a.detail)}</p>`:''}</div>${histMenu(a)}</article>`:view==='Trash'?`<article class="eda-record"><div class="eda-record-main"><b>${H(a.title)}</b><small>${H(a.recordType)} · Deleted ${H(fmtStamp(a.deletedAt))}</small></div><div class="eda-inline-actions">${B('hist-restore','Restore',a.id)}${More([['hist-restore','Restore',a.id],['hist-purge','Delete Permanently',a.id]])}</div></article>`:`<article class="eda-record"><div class="eda-record-main"><div class="eda-record-meta"><span class="eda-chip">${H(a.type)}</span><small>${H(fmtDay(a.date))} · ${H(a.status)}</small></div><button class="eda-record-title" data-eda="hist-record" data-id="${H(a.id)}" data-type="${H(a.type)}">${H(a.title)}</button><p class="eda-clamp">${H(a.body)}</p></div>${More([['hist-record','Open Original',a.id]])}</article>`;
 return `<div class="eda-upgrade">${head('History & Recovery','Find what changed, what was completed and what can be recovered.',B('hist-clear','Reset Filters'))}<div class="eda-tabs eda-history-tabs">${['Activity','Trash','Records'].map(x=>`<button data-eda="hist-view" data-id="${x}" class="${x===view?'active':''}">${x}${x==='Trash'?` (${data.trash.length})`:''}</button>`).join('')}</div>${section(view==='Activity'?'Activity Timeline':view==='Trash'?'Recoverable Trash':'Saved Records',`${filter}<div class="eda-list">${rows.slice(0,uiState.histLimit).map(row).join('')||empty(view==='Trash'?'Your Trash is empty':'No records match these filters','Try another date or section.')}</div><div class="eda-footer"><small class="eda-muted">${rows.length} matching · ${Math.min(rows.length,uiState.histLimit)} displayed</small>${rows.length>uiState.histLimit?B('hist-more','Load more'):''}</div>`)}</div>`;
};

/* ============================ GOOGLE CONNECTIONS ========================= */
function googleStatus(){const g=edaGoogle();const p=data.preferences||{};const canRead=!!g.gmail_read_scope,canCompose=!!g.gmail_scope;
 return {g,p,connected:!!g.connected,calendar:!!g.calendar_scope,canRead,canCompose};}
const dot=(ok,yes,no)=>`<span class="eda-chip ${ok?'good':'muted'}">${ok?H(yes):H(no)}</span>`;
const toggle=(id,label,checked,disabled=false,hint='')=>`<label class="eda-toggle"><span><b>${H(label)}</b>${hint?`<small>${H(hint)}</small>`:''}</span><input type="checkbox" data-eda-change="${id}" ${checked?'checked':''} ${disabled?'disabled':''}></label>`;
googleIntegrationsPage = function(){const {g,p,connected,calendar,canRead,canCompose}=googleStatus();const events=Array.isArray(ui.googleEvents)?ui.googleEvents.slice(0,4):[];
 const account=section('Google Account',`<div class="eda-connection-row">${dot(connected,'Connected','Not Connected')}<b>${H(g.email||'No Google account authorised')}</b></div><p class="eda-muted">${connected?'Permissions are checked per service; access can expire or be revoked.':'Connect using the official Google consent page.'}</p><div class="eda-form-actions">${connected?B('google-status','Refresh Status')+B('google-disconnect2','Disconnect'):B('google-connect2','Connect Google','','',g.configured===false?'disabled':'')}</div>`);
 const cal=section('Google Calendar',`${dot(calendar&&connected,'Authorised','Permission Required')}<p class="eda-muted">Choose which information may flow between Google Calendar and Executive Desk AI. Existing events are never silently deleted.</p>
 ${toggle('calendar-import','Import Google Calendar events',p.edaImportCalendar===true,!calendar)}
 ${toggle('calendar-export','Export app meetings',p.edaExportMeetings===true,!calendar)}
 ${toggle('calendar-tasks','Sync dated tasks and follow-ups (optional)',p.edaExportTasks===true,!calendar)}
 ${toggle('calendar-autosync','Automatic export when app records change',p.googleSync===true,!calendar)}
 <div class="eda-form-actions">${B('google-sync2','Sync Now','',calendar?'':'subtle',calendar?'':'disabled')}${B('google-events2','Load Upcoming Events','',calendar?'subtle':'subtle',calendar?'':'disabled')}${B('google-open2','Open Google Calendar')}</div><small class="eda-muted">Last successful sync: ${H(p.edaLastSync?fmtStamp(p.edaLastSync):'Not yet recorded')} ${p.edaLastSyncError?' · Last error: '+H(p.edaLastSyncError):''}</small>`);
 const gmail=section('Gmail',`${dot(connected&&canRead,'Inbox access granted','Inbox permission missing')} ${dot(connected&&canCompose,'Draft/Compose granted','Compose permission missing')}<p class="eda-muted">Inbox, sending, read/unread and drafts require separate Google OAuth permissions. Gmail activity is managed in Communications, not on this settings page.</p><div class="eda-form-actions">${B('google-permissions','Manage Permissions')}${B('google-communications','Open Communications')}</div>`);
 const eventsHtml=section('Upcoming on Google Calendar',events.length?`<div class="eda-list">${events.map(ev=>`<div class="eda-event"><b>${H(ev.title)}</b><small>${H(ev.all_day?fmtDay(ev.start)+' · All day':fmtStamp(ev.start))}</small><span>${H(ev.location||'')}</span></div>`).join('')}</div>`:empty(calendar?'No upcoming Google events loaded':'Calendar not connected',calendar?'Use Load Upcoming Events above to retrieve current records.':'Connect Google to display authorised Calendar events.'),B('google-events2','Refresh Events','', 'subtle',calendar?'':'disabled'));
 const overview=section('Sync Overview',`<div class="eda-status-list"><span>Calendar</span>${dot(calendar,'Connected','Unavailable')}<span>Gmail Inbox</span>${dot(canRead,'Authorised','Not authorised')}<span>Gmail Drafts</span>${dot(canCompose,'Authorised','Not authorised')}<span>Auto-export</span>${dot(p.googleSync===true,'Enabled','Off')}</div>`);
 const history=section('Sync History',`<div class="eda-list">${(p.edaSyncHistory||[]).slice(0,5).map(x=>`<div class="eda-event"><b>${H(x.result)}</b><small>${H(fmtStamp(x.at))}</small></div>`).join('')||empty('No sync attempts recorded')}</div>`);
 return `<div class="eda-upgrade">${head('Google Connections','Manage permissions, Calendar syncing and Gmail access in one place.')}<div class="eda-two"><div>${account}${cal}${gmail}</div><div>${overview}${eventsHtml}${history}</div></div></div>`;
};

/* Safe sync: no automatic deletion of remote events; no task export by default.
   Existing Google event mappings remain intact and are reused. */
googleSyncRecords = function(){const p=data.preferences||{},out={};
 if(p.edaExportMeetings===true)for(const m of (data.meetings||[])){if(m.status==='Cancelled'||m.googleEventId)continue;const b=meetingCalendarBody(m);if(b)out['meeting:'+m.id]={body:b,hash:JSON.stringify(b)};}
 if(p.edaExportTasks===true){for(const t of (data.tasks||[])){if(t.demo||['Completed','Cancelled'].includes(t.status))continue;const b=taskCalendarBody(t);if(b)out['task:'+t.id]={body:b,hash:JSON.stringify(b)}}for(const f of (data.followups||[])){if(['Completed','Cancelled'].includes(f.status))continue;const b=followupCalendarBody(f);if(b)out['followup:'+f.id]={body:b,hash:JSON.stringify(b)}}}
 return out;
};
googleSyncCalendar = async function(force=false){const {calendar,p}=googleStatus();if(!calendar||(!force&&!p.googleSync)||(!p.edaExportMeetings&&!p.edaExportTasks))return false;if(googleSyncing){googleSyncAgain=true;return false}googleSyncing=true;let changed=false;try{
 const links=data.googleCalendarLinks??={};const desired=googleSyncRecords();
 for(const [key,{body,hash}] of Object.entries(desired)){
  const link=links[key];if(link?.hash===hash)continue;
  try{const remote=link?.eventId?await window.edaCloud.calendarUpdate(link.eventId,body):await window.edaCloud.calendarCreate(body);links[key]={eventId:remote.id||link?.eventId,hash};changed=true;}catch(e){throw new Error(`${key}: ${e.message}`)}
 }
 if(changed)save();return changed;
 }finally{googleSyncing=false;if(googleSyncAgain){googleSyncAgain=false;scheduleGoogleSync()}};
};

/* ======================= GMAIL / COMMUNICATIONS ========================== */
function mailReady(read=false){const g=edaGoogle();return !!(g.connected&&(read?g.gmail_read_scope:g.gmail_scope)&&window.edaCloud?.gmailList)}
function mailBadge(m){const work=(data.gmailWork||{})[m.id]||{},read=!(m.labelIds||[]).includes('UNREAD');return `${!read?'<span class="eda-chip good">Unread</span>':''}${work.status?`<span class="eda-chip">${H(work.status)}</span>`:''}`}
function emailWork(id){data.gmailWork??={};return data.gmailWork[id]??={status:'Pending',updatedAt:now()};}
function folderMatches(m,view){const work=(data.gmailWork||{})[m.id]||{};if(view==='Pending')return work.status==='Pending';if(view==='Awaiting Reply')return work.status==='Awaiting Reply';if(view==='Completed')return work.status==='Completed';return true}
function mailSender(m){const headers=m.headers||{};return headers.from||'(Unknown sender)'}
communicationsPage = function(){const g=edaGoogle();const view=uiState.mailFolder,connected=!!g.connected,live=mailReady(true),selected=uiState.mailDetail,loading=uiState.mailLoading;
 const tabs=['INBOX','UNREAD','Pending','Awaiting Reply','SENT','DRAFT','Completed'];let rows=(uiState.mailRows||[]).filter(x=>folderMatches(x,view));const q=uiState.mailQuery.toLowerCase();if(q)rows=rows.filter(x=>inList([x.snippet,x.headers?.from,x.headers?.subject,x.headers?.to].join(' '),q));
 const row=m=>`<article class="eda-record"><div class="eda-record-main"><div class="eda-record-meta">${mailBadge(m)}<span>${H(fmtStamp(m.internalDate))}</span></div><button data-eda="gmail-open" data-id="${H(m.id)}" class="eda-record-title">${H(m.headers?.subject||'(No subject)')}</button><p><b>${H(mailSender(m))}</b></p><p class="eda-clamp">${H(m.snippet||'')}</p></div>${More([['gmail-open','Open Message',m.id],['gmail-read',m.labelIds?.includes('UNREAD')?'Mark Read':'Mark Unread',m.id],['gmail-pending','Mark Pending',m.id],['gmail-wait','Awaiting Reply',m.id],['gmail-done','Mark Done / Reopen',m.id],['gmail-followup','Create Follow-up',m.id]])}</article>`;
 const msg=selected?`<section class="eda-panel eda-mail-detail"><header class="eda-panelhead"><h2>${H(selected.headers?.subject||'(No subject)')}</h2>${B('gmail-close','Close')}</header><div class="eda-record-meta"><span>From: ${H(selected.headers?.from)}</span><span>To: ${H(selected.headers?.to)}</span><span>${H(fmtStamp(selected.internalDate))}</span></div><div class="eda-mail-body">${H(selected.bodyText||selected.snippet||'No readable text body available.')}</div><div class="eda-form-actions">${B('gmail-reply','Reply',selected.id,'')}${B('gmail-forward','Forward',selected.id)}${B('gmail-read',selected.labelIds?.includes('UNREAD')?'Mark Read':'Mark Unread',selected.id)}${B('gmail-done','Done / Reopen',selected.id)}</div></section>`:'';
 const draft=uiState.mailDraft||{};const compose=uiState.mailCompose?`<form id="eda-gmail-compose" class="eda-form eda-compose">${field('To *','to',draft.to||'','text','required placeholder="recipient@example.com"')}${field('Cc','cc',draft.cc||'')}${field('Bcc','bcc',draft.bcc||'')}${field('Subject *','subject',draft.subject||'','text','required')}${textarea('Message *','body',draft.body||'',9,'required')}<label class="eda-field"><span>Attachments (optional; up to 5 files, 6 MB total)</span><input class="field" type="file" name="attachments" multiple></label><input type="hidden" name="threadId" value="${H(draft.threadId||'')}"><input type="hidden" name="inReplyTo" value="${H(draft.inReplyTo||'')}"><div class="eda-form-actions"><button type="submit" class="btn" name="mode" value="send" ${uiState.mailBusy?'disabled':''}>Send Email</button><button type="submit" class="btn subtle" name="mode" value="draft" ${uiState.mailBusy?'disabled':''}>Save Draft</button>${B('gmail-compose-close','Cancel')}</div></form>`:'';
 return `<div class="eda-upgrade">${head('Communications','Real Gmail messages and independent executive follow-up statuses.',B('gmail-compose-new','+ Compose','','')+B('gmail-open-external','Open Gmail'))}
 <div class="eda-connection-strip">${dot(live,'Inbox authorised','Inbox not authorised')}${connected&&!g.gmail_read_scope?`Inbox permissions are missing — ${B('google-permissions','Manage Permissions')}`:!connected?'Connect your account in Google Connections.':''}</div>
 <div class="eda-tabs">${tabs.map(x=>`<button data-eda="gmail-folder" data-id="${x}" class="${view===x?'active':''}">${x==='INBOX'?'Inbox':x==='SENT'?'Sent':x==='DRAFT'?'Drafts':x==='UNREAD'?'Unread':x}</button>`).join('')}</div>
 ${uiState.mailCompose?section(uiState.mailDraft?.threadId?'Reply / Forward':'Compose Email',compose):''}${msg}
 ${section('Messages',`<div class="eda-toolbar"><input class="field eda-search" id="eda-mail-search" placeholder="Search messages…" value="${H(uiState.mailQuery)}">${B('gmail-refresh','Refresh','',live?'':'subtle',live?'':'disabled')}${B('gmail-add-note','+ Email Note')}</div>${uiState.mailError?`<p class="eda-error">${H(uiState.mailError)}</p>`:''}<div class="eda-list">${loading?'<p class="eda-muted">Loading real Gmail messages…</p>':rows.length?rows.map(row).join(''):empty(live?'No messages found':'Gmail Inbox unavailable',live?'Change the filter or refresh.':'Connect Gmail with read permissions; no sample messages are shown.')}</div>${uiState.mailHasMore?B('gmail-load-more','Load More'):''}`)}
 <details class="eda-note-extra" ${uiState.mailNoteOpen?'open':''}><summary>Manual Email Notes (optional)</summary><p>These notes are stored in your workspace, independent of actual Gmail messages.</p>${B('gmail-add-note',uiState.mailNoteOpen?'Close Note Form':'+ Add Email Note')}${uiState.mailNoteOpen?`<form class="eda-form" id="eda-email-note-form">${field('Sender / contact','from')}${field('Subject *','subject','','text','required')}${textarea('Key details','summary','',3)}<button class="btn" type="submit">Save Email Note</button></form>`:''}<div class="eda-list">${(data.communicationRecords||[]).slice(0,8).map(r=>`<article class="eda-record"><div class="eda-record-main"><b>${H(r.subject)}</b><small>${H(r.from)} · ${H(r.status)}</small><p class="eda-clamp">${H(r.summary)}</p></div></article>`).join('')}</div></details></div>`;
};

/* ============================= INTERACTIONS ============================= */
function saveNote(f){const text=String(f.get('body')||'').trim();if(!text){toast('Write your note before saving.');return}
 const reminder=!!f.get('reminderEnabled'),remindOn=dateOnlyParam(f.get('remindOn')),reminderDate=dateOnlyParam(f.get('reminderDate'));if(reminder&&!reminderDate){toast('Select a reminder date before enabling the notification.');return}
 const existing=byId(data.quickNotes,ui.editQuickNoteId),before=existing?cloneRecord(existing):null;
 const record=existing||{id:newId(),createdAt:now()};Object.assign(record,{title:String(f.get('title')||'').trim(),body:text,category:String(f.get('category')||''),pinned:!!f.get('pinned'),remindOn,reminderDate:reminder?reminderDate:'',reminderEnabled:reminder,reminderTime:reminder?String(f.get('reminderTime')||''):'' ,updatedAt:now()});
 if(!existing)data.quickNotes.unshift(record);ui.editQuickNoteId=null;uiState.noteEditor=false;preserve('Quick Notes',record,existing?'Edited':'Created',before);toast('Note saved to your workspace.');}
function saveMom(f,draft){let title=String(f.get('title')||'').trim(),day=dateOnlyParam(f.get('day'));
 if(!draft&&(!title||!day)){toast('A final MOM needs a discussion title and date.');return}
 if(!draft&&!String(f.get('notes')||'').trim()&&!String(f.get('decisions')||'').trim()){toast('Add discussion notes or decisions to finalise.');return}
 const editing=byId(data.meetingNotes,ui.editMomId),before=editing?cloneRecord(editing):null;const rec=editing||{id:newId(),createdAt:now()};
 const elements=[...document.querySelectorAll('#eda-mom-rows [data-eda-action-row]')];
 const actionItems=elements.map(row=>{const value=n=>row.querySelector(`[name="${n}"]`)?.value||'';return {id:row.dataset.id||newId(),title:value('actionTitle').trim(),owner:value('actionOwner').trim(),dueDate:value('actionDue'),priority:value('actionPriority')||'Normal',status: 'Pending',taskId:value('actionTaskId')}}).filter(x=>x.title);
 // Preserve existing task links and statuses even when editing older action-point rows.
 for(const item of actionItems){const prior=(editing?.actionItems||[]).find(x=>x.id===item.id);if(prior){item.taskId=prior.taskId||item.taskId;item.status=prior.status||item.status}}
 Object.assign(rec,{meetingTitle:title||'Untitled draft',discussionDate:day,discussionTime:String(f.get('time')||''),date:day?day+'T12:00:00+05:30':rec.date||now(),attendees:String(f.get('attendees')||'').trim(),notes:String(f.get('notes')||''),decisions:String(f.get('decisions')||''),actionItems,actions:actionItems.map(x=>x.title),draft,updatedAt:now()});
 if(!editing)data.meetingNotes.unshift(rec);
 if(!draft&&f.get('createTasks')){for(const item of actionItems){if(item.taskId&&byId(data.tasks,item.taskId))continue;const already=(data.tasks||[]).find(t=>t.sourceMom===rec.id&&t.sourceMomAction===item.id);if(already){item.taskId=already.id;continue}const task={id:newId(),title:item.title,person:item.owner,priority:item.priority==='Normal'?'Medium':item.priority,status:'Pending',targetDate:item.dueDate||null,calendarTime:'',createdAt:now(),sourceMom:rec.id,sourceMomAction:item.id};data.tasks.unshift(task);item.taskId=task.id;logActivity('Tasks',task.id,task.title,'Created from MOM action',null,task)}}
 ui.editMomId=null;uiState.momOpen='list';preserve('MOM',rec,editing?(draft?'Draft edited':'Edited'):draft?'Draft saved':'Created',before);toast(draft?'MOM draft saved.':'Meeting minutes saved.');}
function saveTrip(f){const title=String(f.get('title')||'').trim(),start=dateOnlyParam(f.get('start')),end=dateOnlyParam(f.get('end'));
 if(!title||!start||!end){toast('Trip title, departure and return dates are required.');return}if(end<start){toast('Return date cannot be before departure.');return}
 const existing=byId(data.trips,uiState.tripEditId),before=existing?cloneRecord(existing):null,rec=existing||{id:newId(),createdAt:now()};
 function collect(kind){return [...document.querySelectorAll(`#eda-trip-form [data-trip-row="${kind}"]`)].map(row=>{const object={id:row.dataset.id||newId()};row.querySelectorAll('[name]').forEach(input=>object[input.name]=input.value);return object}).filter(obj=>Object.entries(obj).some(([k,v])=>k!=='id'&&v&&v!=='Not Booked'&&v!=='Flight'&&v!=='Pending'));}
 Object.assign(rec,{title,travellers:String(f.get('travellers')||''),city:String(f.get('city')||''),country:String(f.get('country')||''),tripType:String(f.get('tripType')||'Domestic'),start,end,status:String(f.get('status')||'Planning'),notes:String(f.get('notes')||''),agenda:String(f.get('agenda')||''),remindOn:dateOnlyParam(f.get('remindOn')),legs:collect('leg'),hotels:collect('hotel'),groundTransport:collect('ground'),checklist:existing?.checklist||TRIP_CHECKS.map((x,i)=>({id:'basic-'+i,title:x,done:false})),updatedAt:now()});
 if(!existing)data.trips.unshift(rec);uiState.tripSelect=rec.id;uiState.tripEditor=false;uiState.tripEditId='';preserve('Travel',rec,existing?'Edited':'Created',before);toast('Trip saved.');}
function getPdfPayload(type,id){const r=type==='mom'?byId(data.meetingNotes,id):byId(data.trips,id);if(!r)return null;return {kind:type,record:r}}
async function exportPdf(type,id){const payload=getPdfPayload(type,id);if(!payload)return;try{
 const res=await window.edaCloud.exportPdf(payload);if(!res?.blob)throw new Error('No PDF returned');const url=URL.createObjectURL(res.blob),a=document.createElement('a');a.href=url;a.download=`${type==='mom'?'minutes':'travel-itinerary'}-${String(id).slice(0,16)}.pdf`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000);
 }catch(e){toast('PDF could not be generated: '+e.message)}}
function historyOpenRecord(a){if(!a)return;try{memoryOpenSource(a.recordType,a.recordId)}catch(e){toast('Original record unavailable. It may be in Trash.')};}
function openStoredRecord(type,id){try{memoryOpenSource(type,id)}catch(e){toast('Could not open original record.')}}
async function loadMail(reset=true){if(!mailReady(true)){uiState.mailError='Gmail Inbox requires Google read permissions.';refresh();return}
 if(uiState.mailLoading)return;uiState.mailLoading=true;uiState.mailError='';if(reset){uiState.mailCursor=null;uiState.mailRows=[]}refresh();
 try{const view=uiState.mailFolder,remote=view==='UNREAD'?'INBOX':view==='Pending'||view==='Awaiting Reply'||view==='Completed'?'INBOX':view;
 const reply=await window.edaCloud.gmailList({label:remote,max_results:25,page_token:reset?'':uiState.mailCursor||'',query:view==='UNREAD'?'is:unread':''});
 uiState.mailRows=reset?reply.messages:[...uiState.mailRows,...reply.messages.filter(m=>!uiState.mailRows.some(x=>x.id===m.id))];uiState.mailCursor=reply.next_page_token||null;uiState.mailHasMore=!!reply.next_page_token;
 }catch(e){uiState.mailError=e.message}finally{uiState.mailLoading=false;refresh()}}
async function loadMailMessage(id){if(!mailReady(true))return;uiState.mailBusy=true;try{const item=await window.edaCloud.gmailGet(id);uiState.mailSelected=id;uiState.mailDetail=item;refresh()}catch(e){toast('Gmail: '+e.message)}finally{uiState.mailBusy=false}}
function updateWork(id,status){const rec=emailWork(id);const old=cloneRecord(rec);rec.status=status;rec.updatedAt=now();logActivity('Gmail',id,uiState.mailRows.find(x=>x.id===id)?.headers?.subject||'Gmail conversation',status,old,rec);persist()}
async function markRead(id){const m=uiState.mailRows.find(x=>x.id===id)||uiState.mailDetail;if(!m)return;const unread=(m.labelIds||[]).includes('UNREAD');try{await window.edaCloud.gmailSetRead(id,unread);const change=x=>{x.labelIds=(x.labelIds||[]).filter(z=>z!=='UNREAD');if(!unread)x.labelIds.push('UNREAD')};if(uiState.mailDetail?.id===id)change(uiState.mailDetail);uiState.mailRows.filter(x=>x.id===id).forEach(change);refresh()}catch(e){toast('Could not update Gmail read status: '+e.message)}}
async function sendMail(f,mode){if(uiState.mailBusy)return;const to=String(f.get('to')||'').trim(),subject=String(f.get('subject')||'').trim(),body=String(f.get('body')||'');if(!to||!subject||!body.trim()){toast('Recipient, subject and message are required.');return}
 if(mode==='send'&&!confirm('Send this email through your connected Gmail account now?'))return;
 uiState.mailBusy=true;refresh();try{const payload={to,cc:String(f.get('cc')||''),bcc:String(f.get('bcc')||''),subject,body,thread_id:String(f.get('threadId')||''),in_reply_to:String(f.get('inReplyTo')||'')};
 const files=f.getAll('attachments').filter(x=>x&&x.size);
 if(files.length>5||files.reduce((n,x)=>n+x.size,0)>6_000_000)throw new Error('Maximum 5 attachments and 6 MB total.');
 payload.attachments=[];
 for(const file of files){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));payload.attachments.push({filename:file.name,mime_type:file.type||'application/octet-stream',data:btoa(binary)})}
 const result=mode==='send'?await window.edaCloud.gmailSend(payload):await window.edaCloud.gmailSaveDraft(payload);
 const name=mode==='send'?'Sent email':'Saved Gmail draft';logActivity('Gmail',result.message_id||result.draft_id||newId(),subject,name,null,{to,subject,threadId:payload.thread_id,at:now()});
 uiState.mailCompose=false;uiState.mailDraft=null;uiState.mailSelected=null;uiState.mailDetail=null;save();toast(mode==='send'?'Email sent through Gmail.':'Draft saved in Gmail.');await loadMail(true);
 }catch(e){toast((mode==='send'?'Send failed: ':'Draft save failed: ')+e.message)}finally{uiState.mailBusy=false;refresh()}}
async function calendarImport(){if(!ui.googleEvents||!Array.isArray(ui.googleEvents))await googleLoadEvents();const events=ui.googleEvents||[];let imported=0,updated=0;
 for(const e of events){if(!e.id)continue;
  // Our own Google exports are already represented in-app: never import duplicates.
  if(Object.values(data.googleCalendarLinks||{}).some(link=>link.eventId===e.id))continue;
  if(e.all_day){let r=data.tentativeEvents.find(x=>x.googleEventId===e.id);const old=r?cloneRecord(r):null;const info={title:e.title,eventDate:String(e.start).slice(0,10),kind:'Google Calendar',status:e.status||'Scheduled',location:e.location||'',googleEventId:e.id,updatedAt:now()};if(r){Object.assign(r,info);updated++}else{r={id:newId(),...info};data.tentativeEvents.push(r);imported++}logActivity('Tentative Events',r.id,r.title,r?old?'Imported Google update':'Imported from Google':'Imported from Google',old,r);continue}
  let r=data.meetings.find(x=>x.googleEventId===e.id);const old=r?cloneRecord(r):null;const info={title:e.title,at:e.start,location:e.location||'',meetingMethod:e.hangoutLink?'Google Meet':'In person',meetUrl:e.hangoutLink||'',attendees:e.attendees||'',googleEventId:e.id,googleEventUrl:e.htmlLink||'',status:e.status==='cancelled'?'Cancelled':'Scheduled',updatedAt:now()};if(r){Object.assign(r,info);updated++}else{r={id:newId(),...info};data.meetings.push(r);imported++}logActivity('Meetings',r.id,r.title,old?'Imported Google update':'Imported from Google',old,r);
 }
 if(imported||updated)persist();return {imported,updated};}
async function googleSyncSelected(){const p=data.preferences||{};try{let records=0;let outcome={imported:0,updated:0};if(p.edaImportCalendar){await googleLoadEvents();outcome=await calendarImport()}
 if(p.edaExportMeetings||p.edaExportTasks){const before=Object.keys(data.googleCalendarLinks||{}).length;await googleSyncCalendar(true);records=Math.max(0,Object.keys(data.googleCalendarLinks||{}).length-before)}
 const text=`Calendar: ${outcome.imported} imported, ${outcome.updated} updated, ${records} newly exported`;
 p.edaLastSync=now();p.edaLastSyncError='';p.edaSyncHistory=[{at:now(),result:text},...(p.edaSyncHistory||[])].slice(0,60);persist();toast(text);
 }catch(e){p.edaLastSyncError=e.message;p.edaSyncHistory=[{at:now(),result:'Sync failed: '+e.message},...(p.edaSyncHistory||[])].slice(0,60);persist();toast('Calendar sync error: '+e.message)}}

/* New action handlers are separate so existing Daily Plan / Executive Memory /
   Follow-up listeners are not changed. */
document.addEventListener('click',async ev=>{
 const target=ev.target.closest('[data-eda]');if(!target||target.dataset.eda==='trip-check')return;
 ev.preventDefault();ev.stopImmediatePropagation();
 const action=target.dataset.eda,id=target.dataset.id;
 const fail=e=>toast(e?.message||String(e));
 try{switch(action){
 // Notes
 case 'note-new':ui.editQuickNoteId=null;uiState.noteEditor=true;refresh();document.querySelector('.eda-mobile-editor [name="body"]')?.focus();break;
 case 'note-edit':ui.editQuickNoteId=id;uiState.noteEditor=true;refresh();break;
 case 'note-cancel':ui.editQuickNoteId=null;uiState.noteEditor=false;refresh();break;
 case 'note-filter':uiState.noteFilter=id;uiState.noteLimit=25;refresh();break;
 case 'note-more':uiState.noteLimit+=25;refresh();break;
 case 'note-pin':{const r=byId(data.quickNotes,id);if(!r)return;const prev=cloneRecord(r);r.pinned=!r.pinned;r.updatedAt=now();preserve('Quick Notes',r,r.pinned?'Pinned':'Unpinned',prev);break}
 case 'note-reminder':{const r=byId(data.quickNotes,id);if(!r)return;const date=prompt('Reminder date YYYY-MM-DD (blank removes reminder):',r.reminderDate||r.remindOn||'');if(date===null)return;if(date&& !dateOnlyParam(date)){toast('Enter a valid YYYY-MM-DD date.');return}const prev=cloneRecord(r);r.reminderDate=date;r.reminderEnabled=!!date;r.updatedAt=now();preserve('Quick Notes',r,date?'Reminder scheduled':'Reminder removed',prev);break}
 case 'note-upcoming':{const r=byId(data.quickNotes,id);if(!r)return;const date=prompt('Show note in Upcoming on YYYY-MM-DD (blank removes date):',r.remindOn||'');if(date===null)return;if(date&&!dateOnlyParam(date)){toast('Enter a valid YYYY-MM-DD date.');return}const prev=cloneRecord(r);r.remindOn=date;r.updatedAt=now();preserve('Quick Notes',r,date?'Upcoming date updated':'Upcoming date removed',prev);break}
 case 'note-archive':{const r=byId(data.quickNotes,id);if(!r)return;const prev=cloneRecord(r);r.archivedAt=r.archivedAt?null:now();r.updatedAt=now();preserve('Quick Notes',r,r.archivedAt?'Archived':'Unarchived',prev);break}
 case 'note-trash':removeRecord('Quick Notes',id);break;
 // MOM
 case 'mom-add-row':document.querySelector('#eda-mom-rows')?.insertAdjacentHTML('beforeend',momActionRow());break;
 case 'mom-remove-row':target.closest('[data-eda-action-row]')?.remove();break;
 case 'mom-filter':uiState.momFilter=id;uiState.momLimit=25;refresh();break;
 case 'mom-mobile-tab':uiState.momOpen=id==='list'?'list':'write';refresh();break;
 case 'mom-more':uiState.momLimit+=25;refresh();break;
 case 'mom-reset':ui.editMomId=null;uiState.momOpen='write';refresh();break;
 case 'mom-open':case 'mom-edit':ui.editMomId=id;uiState.momOpen='write';refresh();break;
 case 'mom-export':await exportPdf('mom',id);break;
 case 'mom-task-review':{const m=byId(data.meetingNotes,id);const links=actionRows(m).map(x=>x.taskId).filter(Boolean);if(links.length){ui.taskQuery='';nav('Tasks')}else toast('No linked Task Manager actions for this MOM.');break}
 case 'mom-archive':{const m=byId(data.meetingNotes,id);if(!m)return;const prev=cloneRecord(m);m.archivedAt=m.archivedAt?null:now();preserve('MOM',m,m.archivedAt?'Archived':'Unarchived',prev);break}
 case 'mom-trash':removeRecord('MOM',id);break;
 // Travel
 case 'trip-new':uiState.tripEditor=true;uiState.tripEditId='';refresh();break;
 case 'trip-editor-close':uiState.tripEditor=false;uiState.tripEditId='';refresh();break;
 case 'trip-filter':uiState.tripFilter=id;refresh();break;
 case 'trip-select':uiState.tripSelect=id;refresh();break;
 case 'trip-edit':uiState.tripEditId=id;uiState.tripSelect=id;uiState.tripEditor=true;refresh();break;
 case 'trip-add-row':{const parent=document.getElementById(id==='leg'?'eda-trip-legs':id==='hotel'?'eda-trip-hotels':'eda-trip-ground');parent?.insertAdjacentHTML('beforeend',travelRow(id));target.closest('details')?.setAttribute('open','');break}
 case 'trip-remove-row':target.closest('[data-trip-row]')?.remove();break;
 case 'trip-add-check':{const trip=byId(data.trips,id);if(!trip)return;const title=prompt('New checklist item');if(!title?.trim())return;const prev=cloneRecord(trip);trip.checklist=checklistFor(trip);trip.checklist.push({id:newId(),title:title.trim(),done:false});preserve('Travel',trip,'Checklist item added',prev);break}
 case 'trip-reminder':{const t=byId(data.trips,id);if(!t)return;const date=prompt('Travel reminder date YYYY-MM-DD (blank removes):',t.remindOn||'');if(date===null)return;if(date&&!dateOnlyParam(date)){toast('Enter a valid YYYY-MM-DD date.');return}const old=cloneRecord(t);t.remindOn=date;preserve('Travel',t,date?'Reminder set':'Reminder removed',old);break}
 case 'trip-status':{const trip=byId(data.trips,id);if(!trip)return;const options=['Planning','Awaiting Confirmation','Confirmed','In Progress','Completed','Cancelled'];const selection=prompt('Trip status:\n'+options.join(' / '),trip.status||'Planning');if(selection===null)return;const found=options.find(x=>x.toLowerCase()===selection.trim().toLowerCase());if(!found){toast('Choose a supported trip status.');return}if(found==='Cancelled'&&!confirm('Mark trip cancelled? This will NOT cancel external bookings.'))return;setStatus('Travel',data.trips,id,found);break}
 case 'trip-complete':setStatus('Travel',data.trips,id,'Completed');break;
 case 'trip-cancel':if(confirm('Cancel this trip inside Executive Desk AI? External bookings are NOT cancelled.'))setStatus('Travel',data.trips,id,'Cancelled');break;
 case 'trip-trash':removeRecord('Travel',id);break;
 case 'trip-export':await exportPdf('travel',id);break;
 case 'history-travel':uiState.histKind='Travel';goHist('Travel');break;
 // History
 case 'hist-view':ui.historyView=id;uiState.histLimit=40;refresh();break;
 case 'hist-clear':uiState.histQuery='';uiState.histFrom='';uiState.histTo='';uiState.histStatus='All';uiState.histKind='All';ui.edaHistoryKind='All';uiState.histLimit=40;refresh();break;
 case 'hist-more':uiState.histLimit+=40;refresh();break;
 case 'hist-restore':v11RestoreTrash(id);break;
 case 'hist-purge':{const t=byId(data.trash,id);if(!t)return;if(!confirm(`Permanently delete ${t.title}? This cannot be undone.`))return;data.trash=data.trash.filter(x=>x.id!==id);logActivity(t.recordType,t.record?.id||id,t.title,'Permanently deleted');persist();break}
 case 'hist-record':{const r=allRecords().find(x=>x.id===id&&x.type!=='Activity');if(r)openStoredRecord(r.type,r.id);else toast('Record not found.');break}
 case 'hist-open':{const a=byId(data.activities,id);historyOpenRecord(a);break}
 case 'hist-changes':{const a=byId(data.activities,id);if(!a)return;alert(`${a.action}: ${a.title}\n${fmtStamp(a.at)}\n\nBefore:\n${JSON.stringify(a.before||{},null,2).slice(0,4000)}\n\nAfter:\n${JSON.stringify(a.after||{},null,2).slice(0,4000)}`);break}
 case 'hist-reopen':{const a=byId(data.activities,id);if(!a)return;const mapping={'Tasks':data.tasks,'Meetings':data.meetings,'Follow-ups':data.followups,'Travel':data.trips};const arr=mapping[a.recordType],r=arr&&byId(arr,a.recordId);if(!r){toast('The original record is unavailable or already in Trash.');return}if(!['Completed','Cancelled'].includes(r.status)){toast('This record is already active.');return}setStatus(a.recordType,arr,r.id,a.recordType==='Meetings'?'Scheduled':a.recordType==='Travel'?'Planning':'Pending');break}
 // Google
 case 'google-connect2':if(window.edaCloud?.googleConfigured)window.edaCloud.googleStart('link');else toast('Google OAuth credentials are not configured on the server.');break;
 case 'google-status':await window.edaCloud.refreshGoogle();toast('Connection status refreshed.');refresh();break;
 case 'google-disconnect2':if(!confirm('Disconnect Google? Existing app records will remain.'))return;await window.edaCloud.googleDisconnect();toast('Google disconnected without deleting workspace records.');refresh();break;
 case 'google-sync2':await googleSyncSelected();break;
 case 'google-events2':await googleLoadEvents();break;
 case 'google-open2':openExternalUrl('https://calendar.google.com/calendar/u/0/r');break;
 case 'google-permissions':if(window.edaCloud?.googleConfigured){if(confirm('Re-authorise Google to grant missing Calendar or Gmail permissions?'))window.edaCloud.googleStart('link')}else toast('Configure Google OAuth on the backend first.');break;
 case 'google-communications':nav('More','communications');break;
 // Gmail
 case 'gmail-folder':uiState.mailFolder=id;uiState.mailSelected=null;uiState.mailDetail=null;uiState.mailInitialized=true;await loadMail(true);break;
 case 'gmail-refresh':uiState.mailInitialized=true;await loadMail(true);break;
 case 'gmail-load-more':await loadMail(false);break;
 case 'gmail-open':await loadMailMessage(id);break;
 case 'gmail-close':uiState.mailSelected=null;uiState.mailDetail=null;refresh();break;
 case 'gmail-compose-new':uiState.mailCompose=true;uiState.mailDraft={};refresh();break;
 case 'gmail-compose-close':uiState.mailCompose=false;uiState.mailDraft=null;refresh();break;
 case 'gmail-reply':case 'gmail-forward':{const m=uiState.mailDetail;if(!m)return;const subject=m.headers?.subject||'';uiState.mailCompose=true;uiState.mailDraft=action==='gmail-reply'?{to:m.replyTo||m.headers?.replyTo||m.headers?.from||'',subject:/^re:/i.test(subject)?subject:'Re: '+subject,threadId:m.threadId||'',inReplyTo:m.headers?.messageId||'',body:'\n\n'}:{to:'',subject:/^fwd:/i.test(subject)?subject:'Fwd: '+subject,body:'\n\n---- Forwarded message ----\nFrom: '+(m.headers?.from||'')+'\n'+(m.bodyText||m.snippet||'')};refresh();break}
 case 'gmail-read':await markRead(id);break;
 case 'gmail-pending':updateWork(id,'Pending');break;
 case 'gmail-wait':updateWork(id,'Awaiting Reply');break;
 case 'gmail-done':updateWork(id,emailWork(id).status==='Completed'?'Pending':'Completed');break;
 case 'gmail-followup':{const m=uiState.mailRows.find(x=>x.id===id)||uiState.mailDetail;if(!m)return;const old=(data.followups||[]).find(x=>x.gmailMessageId===id);if(old){toast('A follow-up is already linked to this email.');return}const item={id:newId(),title:m.headers?.subject||'Email follow-up',person:m.headers?.from||'',due:null,status:'Pending',gmailMessageId:id,createdAt:now()};data.followups.unshift(item);logActivity('Follow-ups',item.id,item.title,'Created from Gmail',null,item);save();toast('Follow-up created. Add a date in Follow-up Centre.');break}
 case 'gmail-add-note':uiState.mailNoteOpen=!uiState.mailNoteOpen;refresh();break;
 case 'gmail-open-external':openExternalUrl('https://mail.google.com/mail/u/0/');break;
 default:break;
 }}catch(e){fail(e)}
},true);

document.addEventListener('change',ev=>{
 const target=ev.target;
 if(target.matches('[data-eda-change]')){
  ev.stopImmediatePropagation();const key=target.dataset.edaChange;const map={'calendar-import':'edaImportCalendar','calendar-export':'edaExportMeetings','calendar-tasks':'edaExportTasks','calendar-autosync':'googleSync'};
  if(map[key]){data.preferences??={};data.preferences[map[key]]=target.checked;persist();if(target.checked&&key==='calendar-autosync')scheduleGoogleSync()}
  return;
 }
 if(target.matches('[data-eda="trip-check"]')){ev.stopImmediatePropagation();const t=byId(data.trips,target.dataset.tripId);if(!t)return;const old=cloneRecord(t);t.checklist=checklistFor(t).map(c=>c.id===target.dataset.id?{...c,done:target.checked,completedAt:target.checked?now():null}:c);preserve('Travel',t,target.checked?'Checklist completed':'Checklist reopened',old);return}
 if(target.closest('.eda-filters')){ev.stopImmediatePropagation();const key=target.name;if(key==='from')uiState.histFrom=target.value;if(key==='to')uiState.histTo=target.value;if(key==='status')uiState.histStatus=target.value;if(key==='kind'){uiState.histKind=target.value;ui.edaHistoryKind=target.value}uiState.histLimit=40;refresh();return;}
},true);

document.addEventListener('input',ev=>{const id=ev.target.id;if(!['eda-note-search','eda-mom-search','eda-history-query','eda-mail-search'].includes(id))return;
 ev.stopImmediatePropagation();const value=ev.target.value,pos=ev.target.selectionStart;
 if(id==='eda-note-search')ui.noteQuery=value;
 if(id==='eda-mom-search')ui.momSearch=value;
 if(id==='eda-history-query')uiState.histQuery=value;
 if(id==='eda-mail-search')uiState.mailQuery=value;
 refresh();const input=document.getElementById(id);input?.focus();if(input?.setSelectionRange&&Number.isInteger(pos))input.setSelectionRange(pos,pos);
},true);

document.addEventListener('submit',async ev=>{const id=ev.target.id;if(!['eda-note-form','eda-mom-form','eda-trip-form','eda-gmail-compose','eda-email-note-form'].includes(id))return;
 ev.preventDefault();ev.stopImmediatePropagation();const form=new FormData(ev.target);
 try{if(id==='eda-note-form')saveNote(form);
 else if(id==='eda-mom-form')saveMom(form,ev.submitter?.value==='draft');
 else if(id==='eda-trip-form')saveTrip(form);
 else if(id==='eda-gmail-compose')await sendMail(form,ev.submitter?.value==='draft'?'draft':'send');
 else if(id==='eda-email-note-form'){const subject=String(form.get('subject')||'').trim();if(!subject){toast('Subject is required.');return}const rec={id:newId(),subject,from:String(form.get('from')||''),summary:String(form.get('summary')||''),status:'Needs action',createdAt:now()};data.communicationRecords.unshift(rec);logActivity('Email Records',rec.id,rec.subject,'Created',null,rec);uiState.mailNoteOpen=false;persist()}
 }catch(e){toast('Unable to save: '+e.message)}
},true);

// Initialise Gmail only when Communications is opened and read permission exists.
const legacyCommunicationsPage=communicationsPage;
communicationsPage=function(){if(!uiState.mailInitialized&&mailReady(true)){uiState.mailInitialized=true;setTimeout(()=>loadMail(true),0)}return legacyCommunicationsPage()};

// Lightweight, app-open reconciliation. This is not represented as a server-side
// background sync; the server-side integrations remain responsible when closed.
let lastReconcile=0;
window.addEventListener('focus',()=>{
 const p=data.preferences||{};if(!window.edaCloud?.ready||!p.edaImportCalendar||!edaGoogle().calendar_scope)return;
 if(Date.now()-lastReconcile<5*60*1000)return;lastReconcile=Date.now();
 if(ui.tab==='More'&&ui.moreView==='integrations')googleLoadEvents().then(calendarImport).catch(()=>{});
});

// Refresh currently displayed module with upgraded renderers.
if(typeof render==='function')render();
})();
