const fs=require('fs');const esbuild=require('esbuild');
(async()=>{for(const f of ['App.tsx','DecisionLedger.tsx','IntelligenceWorkspaces.tsx']){await esbuild.transform(fs.readFileSync('../frontend/src/'+f,'utf8'),{loader:'tsx',target:'es2020'});console.log(f+': syntax OK');}})().catch(e=>{console.error(e);process.exit(1)});
