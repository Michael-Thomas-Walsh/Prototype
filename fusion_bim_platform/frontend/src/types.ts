export type Discipline='Architecture'|'Structural'|'Plumbing'|'HVAC'|'Electrical'|'Facades'|'Site'|'Other';
export type Element={id:string;baseId:string;name:string;discipline:Discipline;category:string;categoryPath:string;level:string;bounds:[number,number,number,number,number,number]};
export type Issue={id:string;mepId:string;fabricId:string;mepName:string;fabricName:string;pair:string;level:string;type:string;volume:number;status:string;evidence:string;recommendation:string;comment?:string};
export type Activity={id:string;name:string;discipline:string;level:string;start:number;duration:number;progress:number;predecessors:string[];isSynthetic:boolean;elementCount:number};
export type Programme={assumptions:string;activities:Activity[];assignments:Record<string,string[]>};
export const DISCIPLINES:Discipline[]=['Architecture','Structural','HVAC','Plumbing','Electrical','Facades','Site'];
export const COLORS:Record<string,string>={Architecture:'#8da5b9',Structural:'#dda17c',HVAC:'#56d0ba',Plumbing:'#67a6ed',Electrical:'#f2c76d',Facades:'#a5b5cb',Site:'#849b88',Other:'#88919f'};
