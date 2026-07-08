# BybitBot Dashboard — Design System

Terminal de trading crypto/ações. Dark-only, data-dense, legível em volatilidade.

## Typography

- **UI:** Plus Jakarta Sans (400–700)
- **Números / tickers:** IBM Plex Mono (tabular-nums obrigatório em PnL, preços, %)
- Escala: 12 / 13 / 14 / 16 / 20 / 24 / 32 px
- Line-height body: 1.5

## Colors

| Token | Hex | Uso |
|-------|-----|-----|
| `void` | `#05080E` | Fundo app |
| `surface` | `#0A0F18` | Painéis |
| `surface-raised` | `#101722` | Cards |
| `border` | `rgba(148,163,184,0.12)` | Bordas |
| `brand` | `#3D7EFF` | Ações primárias, links, foco |
| `brand-muted` | `#2563EB` | Hover |
| `profit` | `#34D399` | Ganhos |
| `loss` | `#F87171` | Perdas |
| `warn` | `#FBBF24` | Demo / alertas |
| `text` | `#F1F5F9` | Primário |
| `text-muted` | `#94A3B8` | Secundário |
| `text-faint` | `#64748B` | Labels |

## Do's

- Tabular nums em todas as métricas financeiras
- Verde/vermelho consistente para PnL
- Bento grid no overview; tabelas densas em trades
- Um CTA primário por painel de ação
- Feedback de loading em cada fetch

## Don'ts

- Inter, Roboto, gradient text, purple/violet accents
- Cyan-on-dark como cor primária
- Nested cards (>1 nível de borda)
- Emoji como ícones
