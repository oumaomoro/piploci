"""
Modern UI/UX Design System and Stylesheet for Piploci Trading Desk.
Features sleek dark glassmorphism, refined typography, and responsive cards.
"""

DASHBOARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* ── Streamlit Container Reset & Top Spacing Fix ── */
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 1.5rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    max-width: 98% !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
}

/* ── Base Theme & Background ── */
.stApp {
    background: radial-gradient(circle at 50% 0%, #0F172A 0%, #060B12 75%, #030712 100%);
    color: #E2E8F0;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

section[data-testid="stSidebar"] {
    background: #090E17;
    border-right: 1px solid rgba(255, 255, 255, 0.06);
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    color: #F8FAFC;
    letter-spacing: -0.02em;
}

/* ── Custom Glassmorphism Container ── */
.glass-panel {
    background: rgba(15, 23, 42, 0.65);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 12px;
    box-shadow: 0 4px 24px -1px rgba(0, 0, 0, 0.35);
}

/* ── Status Bar ── */
.status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    background: rgba(15, 23, 42, 0.75);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    margin-bottom: 18px;
    flex-wrap: wrap;
    gap: 12px;
}

.status-left, .status-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.status-divider {
    width: 1px;
    height: 16px;
    background: rgba(255, 255, 255, 0.1);
    margin: 0 4px;
}

.status-field {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #94A3B8;
    white-space: nowrap;
}

.status-field strong {
    color: #F1F5F9;
    font-weight: 600;
}

/* ── Badges ── */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 6px;
    font-family: 'Inter', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    white-space: nowrap;
}

.badge-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}

.b-green { 
    background: rgba(16, 185, 129, 0.12); 
    color: #34D399; 
    border: 1px solid rgba(16, 185, 129, 0.28); 
}
.b-green .badge-dot { 
    background: #10B981; 
    box-shadow: 0 0 8px #10B981; 
}

.b-red { 
    background: rgba(239, 68, 68, 0.12); 
    color: #F87171; 
    border: 1px solid rgba(239, 68, 68, 0.28); 
}
.b-red .badge-dot { 
    background: #EF4444; 
    box-shadow: 0 0 8px #EF4444; 
}

.b-amber { 
    background: rgba(245, 158, 11, 0.12); 
    color: #FBBF24; 
    border: 1px solid rgba(245, 158, 11, 0.28); 
}
.b-amber .badge-dot { 
    background: #F59E0B; 
    box-shadow: 0 0 8px #F59E0B; 
}

.b-slate { 
    background: rgba(100, 116, 139, 0.12); 
    color: #94A3B8; 
    border: 1px solid rgba(100, 116, 139, 0.20); 
}
.b-slate .badge-dot { background: #64748B; }

.b-cyan { 
    background: rgba(6, 182, 212, 0.12); 
    color: #38BDF8; 
    border: 1px solid rgba(6, 182, 212, 0.28); 
}
.b-cyan .badge-dot { 
    background: #06B6D4; 
    box-shadow: 0 0 8px #06B6D4; 
}

/* ── Metric Cards ── */
.metric-card {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 16px 20px;
    position: relative;
    overflow: hidden;
    transition: transform 0.2s ease, border-color 0.2s ease;
}

.metric-card:hover {
    border-color: rgba(56, 189, 248, 0.35);
    transform: translateY(-2px);
}

.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.4), transparent);
}

.mc-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}

.mc-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.45rem;
    font-weight: 700;
    color: #F8FAFC;
    line-height: 1.15;
}

.mc-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    color: #94A3B8;
    margin-top: 6px;
}

.mc-positive { color: #34D399 !important; }
.mc-negative { color: #F87171 !important; }
.mc-neutral  { color: #94A3B8 !important; }

/* ── Risk Panel & Gauge ── */
.risk-panel {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 20px;
}

.risk-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}

.risk-title {
    font-family: 'Inter', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.risk-reading {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    font-weight: 600;
}

.risk-bar-bg {
    width: 100%;
    height: 7px;
    background: rgba(2, 6, 23, 0.7);
    border-radius: 4px;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.04);
}

.risk-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.risk-tiers {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
}

.risk-tier-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.62rem;
    color: #475569;
}

/* ── Compounding Panel ── */
.compounding-panel {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 20px;
}

.comp-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
    flex-wrap: wrap;
    gap: 8px;
}

.comp-title {
    font-family: 'Inter', sans-serif;
    font-size: 0.80rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #F1F5F9;
    display: flex;
    align-items: center;
    gap: 8px;
}

.comp-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 14px;
}

.comp-card {
    background: rgba(2, 6, 23, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 12px 14px;
}

.comp-card-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.64rem;
    font-weight: 600;
    color: #64748B;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
}

.comp-card-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.18rem;
    font-weight: 700;
    color: #F8FAFC;
}

.comp-card-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.64rem;
    color: #94A3B8;
    margin-top: 3px;
}

.milestone-bar-bg {
    width: 100%;
    height: 8px;
    background: rgba(2, 6, 23, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 4px;
    overflow: hidden;
    margin: 8px 0;
}

.milestone-bar-fill {
    height: 100%;
    border-radius: 4px;
    transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* ── Instrument Cards ── */
.inst-card {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 18px 20px;
    height: 100%;
}

.inst-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.inst-symbol {
    font-family: 'Inter', sans-serif;
    font-size: 1.10rem;
    font-weight: 700;
    color: #F8FAFC;
    letter-spacing: -0.01em;
}

.inst-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.70rem;
    color: #94A3B8;
}

/* ── Streamlit Tabs Styling ── */
div[data-testid="stTabs"] button[data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    color: #64748B !important;
    padding: 10px 20px !important;
    border-radius: 6px 6px 0 0 !important;
}

div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #38BDF8 !important;
    background: rgba(56, 189, 248, 0.08) !important;
    border-bottom: 2px solid #38BDF8 !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    padding: 6px 12px !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    transition: all 0.2s ease !important;
}

/* ── Table & DataFrames ── */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 8px;
    overflow: hidden;
}
</style>
"""
