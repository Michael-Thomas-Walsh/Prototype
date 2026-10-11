import {useMemo} from 'react';
import type {Issue,Activity} from './types';
export type DeliveryPlan={title:string;status:string;workPackages:{id:string;name:string;owner:string;plannedWeek:number;plannedDuration:number}[];deliverables:{id:string;title:string;workPackageId:string;targetWeek:number;status:string;revision:string}[];issueImpacts:{issueId:string;activityIds:string[];workPackageIds:string[];drawingIds:string[];earliestAffectedWeek:number|null;impactStatus:string}[]};
export function ImpactPanel({issue,plan,activities,onChooseActivity}:{issue:Issue|null;plan:DeliveryPlan|null;activities:Activity[];onChooseActivity:(a:Activity)=>void}){
 const impact=useMemo(()=>plan?.issueImpacts.find(x=>x.issueId===issue?.id),[plan,issue]);
 if(!issue)return <div className="impact-panel"><h3>Delivery impact intelligence</h3><p>Select a coordination issue to see which fictional work packages, construction activities and drawings might need review.</p><span className="blue-label">Prototype TIDP · illustrative</span></div>;
 const acts=activities.filter(a=>impact?.activityIds.includes(a.id));
 const packs=plan?.workPackages.filter(p=>impact?.workPackageIds.includes(p.id))||[];
 const drawings=plan?.deliverables.filter(d=>impact?.drawingIds.includes(d.id))||[];
 return <div className="impact-panel"><div className="impact-heading"><h3>Potential delivery impact</h3><span className="warning-label">Inferred, not verified</span></div><p>Issue <strong>{issue.id}</strong> references model elements mapped to the following assumed delivery obligations.</p>
 <div className="impact-metrics"><div><b>{packs.length}</b><span>Work packages</span></div><div><b>{drawings.length}</b><span>Drawing deliverables</span></div><div><b>{acts.length}</b><span>Activities</span></div></div>
 <h4>Impacted construction activities</h4><div className="impact-items">{acts.map(a=><button key={a.id} onClick={()=>onChooseActivity(a)}>{a.id} · {a.name}<span>Week {a.start}–{a.start+a.duration}</span></button>)}</div>
 <h4>Work packages / responsibility</h4><div className="impact-items">{packs.map(p=><div key={p.id}><strong>{p.id}</strong> {p.name}<span>{p.owner}</span></div>)}</div>
 <h4>TIDP drawing deliverables</h4><div className="impact-items">{drawings.map(d=><div key={d.id}><strong>{d.id}</strong> {d.title}<span>{d.revision} · Target W{d.targetWeek} · {d.status}</span></div>)}</div>
 <p className="small-note">Illustrative TIDP: package ownership, planned dates and drawings are fictional. These are potential review dependencies, not approved drawing links, programme delays or confirmed clashes.</p></div>;
}
