"""Issue intelligence: traceable local evidence, reviewer decision, optional Gemini and BCF 2.1 export."""
import io, json, os, sqlite3, urllib.request, urllib.error, uuid, zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

class Review(BaseModel):
    classification: str = Field(max_length=80)
    decision: str = Field(max_length=40)
    reason: str = Field(max_length=2000)

class AnalysisRequest(BaseModel):
    use_gemini: bool = False

def register(app, read, conn, issue_provider, programme_provider, cpm_fn, groups_fn, root):
    def review_conn():
        db=conn()
        db.execute('CREATE TABLE IF NOT EXISTS issue_decisions(issue_id TEXT PRIMARY KEY, classification TEXT, decision TEXT, reason TEXT, recorded_at TEXT, source_version TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS sheet_links(model_key TEXT NOT NULL,element_id TEXT NOT NULL,view_id TEXT NOT NULL,sheet_id TEXT NOT NULL,sheet_number TEXT,sheet_name TEXT,view_name TEXT,document_title TEXT,source TEXT NOT NULL,PRIMARY KEY(model_key,element_id,view_id,sheet_id))')
        return db

    def issue_by_id(issue_id):
        result=next((x for x in issue_provider() if x['id']==issue_id),None)
        if result is None:raise HTTPException(404,'Unknown coordination issue')
        return result

    def evidence(issue_id):
        issue=issue_by_id(issue_id)
        p=programme_provider()
        plan=read('delivery_plan.json')
        elements=[issue['mepId'],issue['fabricId']]
        base_ids={i.split('_t',1)[0] for i in elements}
        linked_acts=[{'id':a['id'],'name':a['name'],'duration':a['duration']} for a in p['activities'] if any(e.split('_t',1)[0] in base_ids for e in p['assignments'].get(a['id'],[]))]
        linked_act_ids={a['id'] for a in linked_acts}
        packages=[{'id':w['id'],'name':w['name']} for w in plan['workPackages'] if any(i in linked_act_ids for i in w['activityIds'])]
        pkg_ids={w['id'] for w in packages}
        drawings=[{'id':d['id'],'title':d['title'],'evidence':'SYNTHETIC_TIDP_WORK_PACKAGE'} for d in plan['deliverables'] if d['workPackageId'] in pkg_ids][:30]
        with review_conn() as db:
            links=[dict(r) for r in db.execute('SELECT element_id,model_key,sheet_number,sheet_name,view_id FROM sheet_links WHERE element_id IN (?,?) LIMIT 100', tuple(base_ids) if len(base_ids)==2 else (next(iter(base_ids)),next(iter(base_ids))))] if len(base_ids)>0 else []
            row=db.execute('SELECT * FROM issue_decisions WHERE issue_id=?',(issue_id,)).fetchone()
            decision=dict(row) if row else None
        return {'issue':issue,'elements':elements,'activities':linked_acts,'workPackages':packages,'proposedDrawings':drawings,'revitViewCollectorLinks':links,'review':decision,'provenance':{'geometry':'AABB_CANDIDATE_NOT_CONFIRMED','programme':'SYNTHETIC','drawingSuggestions':'SYNTHETIC','revitLinks':'VIEW_MEMBERSHIP_CANDIDATE_UNVERIFIED_REVISION'},'caution':'Candidate overlap is not a verified collision. Exported view collector membership is not proof of printed drawing visibility. Source model versions have not been reconciled.'}

    @app.get('/api/coordination/issues/{issue_id}/evidence')
    def issue_evidence(issue_id:str):return evidence(issue_id)

    @app.get('/api/coordination/issues/{issue_id}/graph')
    def issue_graph(issue_id:str):
        d=evidence(issue_id)
        nodes=[{'id':issue_id,'type':'coordination_issue','label':issue_id}]
        edges=[];ids={issue_id}
        def add(item,kind,relation,origin=issue_id):
            key=item['id'];
            if key not in ids:nodes.append({'id':key,'type':kind,'label':item.get('name',item.get('title',key))});ids.add(key)
            edges.append({'source':origin,'target':key,'relation':relation,'evidence':'SYNTHETIC' if kind in ('activity','work_package','tidp_drawing') else 'EXPORTED_SOURCE'})
        for eid in d['elements']:add({'id':eid},'model_element','INVOLVES')
        for a in d['activities']:add(a,'activity','MAY_AFFECT')
        for w in d['workPackages']:add(w,'work_package','MAY_IMPACT')
        for s in d['proposedDrawings']:add(s,'tidp_drawing','SUGGESTS_REVIEW')
        for link in d['revitViewCollectorLinks']:
            sid='SHEET:'+link['model_key']+':'+link['sheet_number']
            add({'id':sid,'name':link['sheet_name']},'revit_sheet','VIEW_COLLECTOR_ASSOCIATION',link['element_id'])
        return {'root':issue_id,'nodes':nodes,'edges':edges,'caution':d['caution']}

    @app.post('/api/coordination/issues/{issue_id}/review')
    def save_review(issue_id:str,payload:Review):
        issue_by_id(issue_id)
        if payload.decision not in ('Accept recommendation','Reject recommendation','Needs investigation','Closed'):raise HTTPException(400,'Invalid decision')
        if not payload.reason.strip():raise HTTPException(400,'Review reasoning required')
        now=datetime.now(timezone.utc).isoformat()
        with review_conn() as db:
            db.execute('INSERT INTO issue_decisions VALUES(?,?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET classification=excluded.classification, decision=excluded.decision, reason=excluded.reason, recorded_at=excluded.recorded_at, source_version=excluded.source_version',(issue_id,payload.classification,payload.decision,payload.reason,now,read('metadata.json').get('version_id','unknown')))
        return {'issue_id':issue_id,'decision':payload.decision,'recorded_at':now}

    def local_analysis(d):
        issue=d['issue']; pair=(issue.get('pair') or '').lower()
        classification='Potential service-to-structure coordination issue' if any(x in pair for x in ('struct','beam','wall')) else 'Potential multidisciplinary coordination issue'
        return {'provider':'DETERMINISTIC_LOCAL','classification':classification,'grouping':'Review with other candidates sharing the MEP element and level','explanation':'This is an AABB overlap candidate. Review real surface meshes and identify whether clearance or penetration is required.','confidence':None,'recommendedActions':['Inspect both transformed meshes in the 3D viewer','Check host specification and relevant fire / structural design requirements','Confirm affected drawings and model version provenance','Record a reviewer decision'],'evidenceIds':[issue['id'],issue['mepId'],issue['fabricId']],'notVerified':['Physical clash','Printed drawing visibility','Programme delay'],'humanApprovalRequired':True}

    @app.post('/api/coordination/issues/{issue_id}/analyse')
    def analyse(issue_id:str,req:AnalysisRequest):
        d=evidence(issue_id);fallback=local_analysis(d)
        if not req.use_gemini:return fallback
        token=os.environ.get('GEMINI_API_KEY','').strip()
        if not token:raise HTTPException(503,'Gemini is not configured. Set GEMINI_API_KEY in the backend environment; local analysis remains available.')
        # Deliberately send a small redacted evidence subset; no proprietary parameter payload, geometry, file paths or documents.
        issue=d['issue']
        packet={'issueId':issue_id,'disciplinePair':issue.get('pair'),'level':issue.get('level'),'candidateOverlapVolume':issue.get('volume'),'candidateStatus':'AABB_ONLY','linkedActivityCount':len(d['activities']),'suggestedDrawingCount':len(d['proposedDrawings']),'revitViewLinksCount':len(d['revitViewCollectorLinks'])}
        prompt='You are an AEC coordination triage assistant. All geometry is broad-phase AABB only. Do not claim confirmed clashes, compliance, sheet visibility or schedule delays. Return strictly JSON with keys classification, grouping, explanation, confidence (0..1), recommendedActions (array of strings), evidenceIds (array, use issueId only), notVerified (array). Evidence: '+json.dumps(packet)
        model=os.environ.get('GEMINI_MODEL','gemini-2.5-flash')
        if not all(c.isalnum() or c in '.-_' for c in model):raise HTTPException(400,'Invalid Gemini model setting')
        url='https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent'
        body={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','temperature':0.1}}
        request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','x-goog-api-key':token},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=20) as response:result=json.load(response)
            raw=''.join(x.get('text','') for x in result['candidates'][0]['content']['parts'])
            output=json.loads(raw)
            for k in ('classification','grouping','explanation','recommendedActions'):
                if k not in output:raise ValueError('AI response missing '+k)
            output.update({'provider':'GEMINI_ADVISORY','humanApprovalRequired':True,'evidencePacket':packet,'caution':'AI classification is unverified and requires human review.'})
            return output
        except (urllib.error.URLError,KeyError,IndexError,ValueError,TimeoutError) as ex:
            raise HTTPException(502,'Gemini analysis failed; use the local rules-based option. '+str(ex)[:180])

    @app.get('/api/coordination/issues/{issue_id}/bcf')
    def bcf_export(issue_id:str):
        d=evidence(issue_id); issue=d['issue']; doc=read('metadata.json');namespace='http://www.buildingsmart-tech.org/bcf/2.1'
        def sub(p,t,v=None):
            e=ET.SubElement(p,t)
            if v is not None:e.text=str(v)
            return e
        topic=ET.Element('Markup');topic.set('xmlns',namespace)
        hdr=sub(topic,'Header');file=sub(hdr,'File');sub(file,'Filename','Fusion BIM Intelligence (prototype)')
        t=sub(topic,'Topic');t.set('Guid',str(uuid.uuid5(uuid.NAMESPACE_URL,'fusion-bim:'+issue_id)));t.set('TopicType','Issue');t.set('TopicStatus','Open')
        sub(t,'Title','Coordination candidate '+issue_id)
        sub(t,'Description','AABB broad-phase candidate; no confirmed triangle collision. Involves '+str(issue['mepId'])+' and '+str(issue['fabricId'])+'. Sheet and programme relationships are unverified or synthetic.')
        sub(t,'CreationDate',datetime.now(timezone.utc).isoformat());sub(t,'CreationAuthor','Fusion BIM Intelligence Prototype')
        gid=str(uuid.uuid5(uuid.NAMESPACE_URL,'fusion-bim:'+issue_id))
        view_guid=str(uuid.uuid5(uuid.NAMESPACE_URL,'fusion-bim:view:'+issue_id))
        viewpoints=sub(topic,'Viewpoints'); ref=sub(viewpoints,'ViewPoint');ref.set('Guid',view_guid);ref.text='viewpoint.bcfv'
        view=ET.Element('VisualizationInfo');view.set('Guid',view_guid)
        comps=sub(view,'Components'); sel=sub(comps,'Selection')
        for eid in d['elements']:
            x=sub(sel,'Component');x.set('OriginatingSystem','Speckle/Revit prototype');x.set('AuthoringToolId',eid)
        # Saved camera is calculated from the involved element bounds in Fusion's
        # display coordinates; it is an illustrative issue viewpoint, not a
        # previously captured reviewer camera/snapshot.
        try:
            model=read('elements.json'); lookup={e['id']:e for e in model}
            bounds=[lookup[eid]['bounds'] for eid in d['elements'] if eid in lookup]
            if bounds:
                lo=[min(b[0] for b in bounds),min(b[2] for b in bounds),min(-b[4] for b in bounds)]
                hi=[max(b[3] for b in bounds),max(b[5] for b in bounds),max(-b[1] for b in bounds)]
                centre=[(a+b)/2 for a,b in zip(lo,hi)]
                span=max(4,max(b-a for a,b in zip(lo,hi)))
            else:centre=[0.,0.,0.];span=25.
        except Exception:centre=[0.,0.,0.];span=25.
        camera=sub(view,'PerspectiveCamera')
        cp=sub(camera,'CameraViewPoint')
        for a,value in zip(('X','Y','Z'),(centre[0]+span,centre[1]+span*.7,centre[2]+span)):sub(cp,a,round(value,5))
        direction=sub(camera,'CameraDirection')
        for a,value in zip(('X','Y','Z'),(-1.,-.7,-1.)):sub(direction,a,value)
        up=sub(camera,'CameraUpVector')
        for a,value in zip(('X','Y','Z'),(0.,1.,0.)):sub(up,a,value)
        sub(camera,'FieldOfView',60)
        project=ET.Element('Version');project.set('VersionId','2.1')
        zbuf=io.BytesIO()
        with zipfile.ZipFile(zbuf,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('bcf.version',ET.tostring(project,encoding='utf-8',xml_declaration=True))
            z.writestr(gid+'/markup.bcf',ET.tostring(topic,encoding='utf-8',xml_declaration=True))
            z.writestr(gid+'/viewpoint.bcfv',ET.tostring(view,encoding='utf-8',xml_declaration=True))
        zbuf.seek(0)
        return StreamingResponse(zbuf,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="'+issue_id+'.bcfzip"'})

    @app.get('/api/programme/cpm/scenario')
    def scenario(activity_id:str,added_weeks:int=0):
        if added_weeks<0 or added_weeks>52:raise HTTPException(422,'added_weeks must be 0..52')
        p=programme_provider();activities=[dict(a) for a in p['activities']]
        if activity_id not in {a['id'] for a in activities}:raise HTTPException(404,'Unknown activity')
        synthetic=all(not a.get('predecessors') for a in activities)
        if synthetic:
            ranked=sorted(activities,key=lambda a:(a.get('start',0),a['id']))[:8]
            for a,b in zip(ranked,ranked[1:]):b['predecessors']=[a['id']]
        original=cpm_fn(activities)
        next(a for a in activities if a['id']==activity_id)['duration']+=added_weeks
        modified=cpm_fn(activities)
        return {'activityId':activity_id,'addedWeeks':added_weeks,'baselineFinish':original['projectFinishWeek'],'scenarioFinish':modified['projectFinishWeek'],'finishDelta':modified['projectFinishWeek']-original['projectFinishWeek'],'scenario':modified,'syntheticDependencies':synthetic,'warning':'Hypothetical delay and synthetic dependencies; not a forecast of actual project programme.'}
