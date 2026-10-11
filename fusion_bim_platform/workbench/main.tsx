import React from 'react';
import {createRoot} from 'react-dom/client';
import DecisionLedger from '../frontend/src/DecisionLedger';
import '../frontend/src/style.css';
import './workbench.css';
createRoot(document.getElementById('root')!).render(<main className="standalone"><header><span>FUSION</span><small>ENGINEERING INTELLIGENCE · LOCAL PROTOTYPE</small></header><DecisionLedger/></main>);
