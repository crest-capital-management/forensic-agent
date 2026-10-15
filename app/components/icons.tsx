// Icons come from lucide-react (clean 1.5px line icons). Thin wrappers keep one place to change size and weight.
import {
  BarChart3, Briefcase, FileText, Grid3x3, Columns2, Ellipsis, Home, Maximize2, Minimize2, Search, SendHorizontal, SlidersHorizontal,
  Sparkles, SquarePen, Star,
} from "lucide-react";

type P = { size?: number };
const W = 1.6;

export const IconHome = ({ size = 20 }: P) => <Home size={size} strokeWidth={W} aria-hidden />;
export const IconMemos = ({ size = 20 }: P) => <FileText size={size} strokeWidth={W} aria-hidden />;
export const IconCases = ({ size = 20 }: P) => <Briefcase size={size} strokeWidth={W} aria-hidden />;
export const IconCompare = ({ size = 20 }: P) => <Columns2 size={size} strokeWidth={W} aria-hidden />;
export const IconConfig = ({ size = 20 }: P) => <SlidersHorizontal size={size} strokeWidth={W} aria-hidden />;
export const IconAnalysis = ({ size = 20 }: P) => <Grid3x3 size={size} strokeWidth={W} aria-hidden />;
export const IconDashboard = ({ size = 20 }: P) => <BarChart3 size={size} strokeWidth={W} aria-hidden />;
export const IconSparkle = ({ size = 20 }: P) => <Sparkles size={size} strokeWidth={W} aria-hidden />;
export const IconNewChat = ({ size = 20 }: P) => <SquarePen size={size} strokeWidth={W} aria-hidden />;
export const IconExpand = ({ size = 20 }: P) => <Maximize2 size={size} strokeWidth={W} aria-hidden />;
export const IconCollapse = ({ size = 20 }: P) => <Minimize2 size={size} strokeWidth={W} aria-hidden />;
export const IconSend = ({ size = 20 }: P) => <SendHorizontal size={size} strokeWidth={W} aria-hidden />;
export const IconSearch = ({ size = 20 }: P) => <Search size={size} strokeWidth={W} aria-hidden />;
export const IconDots = ({ size = 20 }: P) => <Ellipsis size={size} strokeWidth={W} aria-hidden />;
export const IconStar = ({ size = 20 }: P) => <Star size={size} strokeWidth={W} fill="currentColor" aria-hidden />;

// The CREST wordmark: the text "CREST" in the Maharlika font (file goes in public/fonts, see globals.css).
export function Wordmark() {
  return <span className="wordmark">CREST</span>;
}
