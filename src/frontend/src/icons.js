// Inline SVG icons (Lucide, ISC license) and SVG country flags (flag-icons, MIT).
import 'flag-icons/css/flag-icons.min.css';
import {
  ArrowLeft, BookOpen, Banknote, Clock, ExternalLink, Globe, Grid3x3, Hash, Landmark,
  MapPin, Maximize, Phone, Sparkles, TrendingUp, User, Users, Wallet, X, ChevronDown, Info, Newspaper,
  Languages, HandHeart, Hourglass, Car,
  Baby, Stethoscope, Bed, Syringe, Droplet, Cigarette, HeartPulse, Wind,
} from 'lucide-static';

const ICONS = {
  'arrow-left': ArrowLeft, 'book-open': BookOpen, banknote: Banknote, clock: Clock,
  'external-link': ExternalLink, globe: Globe, grid: Grid3x3, hash: Hash, landmark: Landmark,
  'map-pin': MapPin, maximize: Maximize, phone: Phone, sparkles: Sparkles,
  'trending-up': TrendingUp, user: User, users: Users, wallet: Wallet, x: X,
  'chevron-down': ChevronDown, info: Info, newspaper: Newspaper,
  languages: Languages, 'hand-heart': HandHeart, hourglass: Hourglass, car: Car,
  baby: Baby, stethoscope: Stethoscope, bed: Bed, syringe: Syringe, droplet: Droplet,
  cigarette: Cigarette, 'heart-pulse': HeartPulse, wind: Wind,
};

/** Returns an inline <svg> string for a Lucide icon, sized via CSS (.ico). */
export function icon(name, cls = '') {
  const svg = ICONS[name];
  if (!svg) return '';
  return svg.replace('<svg', `<svg aria-hidden="true" focusable="false"`).replace(/class="[^"]*"/, `class="ico ${cls}"`);
}

/** Country flag as an SVG background (4:3). Falls back to a neutral placeholder. */
export function flag(iso2, cls = '') {
  const code = /^[A-Za-z]{2}$/.test(iso2 ?? '') ? iso2.toLowerCase() : 'xx';
  return `<span class="fi fi-${code} flag-img ${cls}" aria-hidden="true"></span>`;
}
