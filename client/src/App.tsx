import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Activity, LayoutDashboard, Search, Users, Trophy, BarChart2, BookOpen, Brain, Target, Info, AlertTriangle } from 'lucide-react';
import { CommandDesk, MatchCentre, HeadToHeadLab, PlayerIntel, TournamentCentre, Rankings, Methodology, Analyst, Accuracy } from './pages';

function NavItem({ to, icon: Icon, label }: { to: string, icon: any, label: string }) {
  const location = useLocation();
  const isActive = location.pathname === to;
  return (
    <Link to={to} className={`flex items-center gap-3 px-4 py-2 my-1 text-sm font-mono tracking-wide ${isActive ? 'text-acid border-l-2 border-acid bg-panel-strong' : 'text-muted hover:text-paper hover:bg-panel'}`}>
      <Icon className="w-4 h-4" />
      <span className="uppercase">{label}</span>
    </Link>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col md:flex-row relative z-10">
      <div className="fixed top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-acid/5 blur-[120px] rounded-full pointer-events-none" />

      <aside className="hidden md:flex flex-col w-[164px] border-r border-line bg-ink/80 backdrop-blur shrink-0 fixed h-full z-20">
        <div className="p-4 border-b border-line">
          <div className="font-display font-bold text-lg leading-tight tracking-widest text-paper">
            BWF //
            <br />
            <span className="text-acid">SUPERCOMPUTER</span>
          </div>
        </div>
        <nav className="flex-1 py-4 overflow-y-auto">
          <NavItem to="/" icon={LayoutDashboard} label="Command Desk" />
          <NavItem to="/matches" icon={Activity} label="Match Centre" />
          <NavItem to="/h2h" icon={Users} label="H2H Lab" />
          <NavItem to="/players" icon={Search} label="Player Intel" />
          <NavItem to="/tournaments" icon={Trophy} label="Tournaments" />
          <NavItem to="/rankings" icon={BarChart2} label="Rankings" />
          <NavItem to="/methodology" icon={BookOpen} label="Methodology" />
          <NavItem to="/analyst" icon={Brain} label="AI Analyst" />
          <NavItem to="/accuracy" icon={Target} label="Accuracy" />
        </nav>
      </aside>

      <header className="md:hidden flex flex-col border-b border-line bg-ink/90 backdrop-blur sticky top-0 z-30">
        <div className="p-3 border-b border-line flex items-center justify-between">
           <div className="font-display font-bold tracking-widest text-paper text-sm">
            BWF // <span className="text-acid">SUPERCOMPUTER</span>
          </div>
        </div>
        <nav className="flex overflow-x-auto p-2 scrollbar-hide">
          <NavItem to="/" icon={LayoutDashboard} label="Desk" />
          <NavItem to="/matches" icon={Activity} label="Matches" />
          <NavItem to="/h2h" icon={Users} label="H2H" />
          <NavItem to="/players" icon={Search} label="Players" />
          <NavItem to="/tournaments" icon={Trophy} label="Events" />
          <NavItem to="/rankings" icon={BarChart2} label="Rankings" />
          <NavItem to="/methodology" icon={BookOpen} label="Methodology" />
          <NavItem to="/analyst" icon={Brain} label="Analyst" />
          <NavItem to="/accuracy" icon={Target} label="Accuracy" />
        </nav>
      </header>

      <main className="flex-1 md:ml-[164px] flex flex-col min-h-screen">
        <div className="h-[58px] border-b border-line bg-panel/50 backdrop-blur flex items-center px-4 justify-between shrink-0 sticky top-0 z-20">
           <div className="flex items-center gap-3">
             <div className="h-2 w-2 rounded-full bg-acid shadow-[0_0_8px_var(--color-acid)] animate-pulse" />
             <span className="font-mono text-xs text-acid uppercase tracking-wider">Provider / operational</span>
           </div>
           <div className="font-mono text-xs text-muted flex items-center gap-4">
             <span className="hidden sm:inline">Provider contract / website-2026-08</span>
             <div className="flex items-center gap-1 border-l border-line pl-4">
               <Info className="w-3 h-3" />
               <span className="hidden sm:inline">Data lineage / inspectable</span>
             </div>
           </div>
        </div>
        
        <div className="bg-panel-strong border-b border-line p-3 flex gap-3 text-xs font-mono items-start">
          <AlertTriangle className="w-4 h-4 text-amber shrink-0 mt-0.5" />
          <p className="text-muted leading-relaxed">
            Provider records are normalized through the website server. While the connection is verifying, no fixture or inferred record is shown. Unsupported capabilities remain explicitly withheld.
          </p>
        </div>

        <div className="p-4 md:p-[18px] w-full max-w-[1600px] mx-auto flex-1">
          {children}
        </div>

        <footer className="mt-auto border-t border-line bg-panel p-6">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4 text-xs font-mono text-muted">
            <div className="flex items-center gap-2">
               <div className="w-4 h-4 border border-acid rotate-45 flex items-center justify-center">
                 <div className="w-1.5 h-1.5 bg-acid" />
               </div>
               <span className="uppercase tracking-widest">BWF Supercomputer / Foundation interface</span>
            </div>
            <span className="uppercase tracking-wide opacity-50">Explainable by design / Built for validated data</span>
          </div>
        </footer>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<CommandDesk />} />
          <Route path="/matches" element={<MatchCentre />} />
          <Route path="/h2h" element={<HeadToHeadLab />} />
          <Route path="/players" element={<PlayerIntel />} />
          <Route path="/tournaments" element={<TournamentCentre />} />
          <Route path="/rankings" element={<Rankings />} />
          <Route path="/methodology" element={<Methodology />} />
          <Route path="/analyst" element={<Analyst />} />
          <Route path="/accuracy" element={<Accuracy />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
