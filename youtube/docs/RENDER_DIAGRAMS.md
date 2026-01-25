# Architecture Diagram Rendering Guide

This folder contains multiple architecture diagram formats. Choose based on your preference:

---

## 📊 Available Formats

### 1. PlantUML (ARCHITECTURE.puml)
**Best for:** Traditional enterprise architecture diagrams

**Render Options:**
```bash
# Online: 
# Visit https://www.plantuml.com/plantuml/uml/
# Paste ARCHITECTURE.puml content

# CLI (if PlantUML installed):
plantuml ARCHITECTURE.puml
# Generates: ARCHITECTURE.png

# VS Code Extension:
# Install "PlantUML" by jebbs
# Right-click -> "PlantUML: Preview Current Diagram"
```

### 2. D2 (ARCHITECTURE.d2)
**Best for:** Modern, clean architecture diagrams

**Render Options:**
```bash
# Install D2:
curl -fsSL https://d2lang.com/install.sh | sh -s --

# Render:
d2 ARCHITECTURE.d2 ARCHITECTURE.svg
d2 ARCHITECTURE.d2 ARCHITECTURE.png

# With layout engine:
d2 --layout elk ARCHITECTURE.d2 ARCHITECTURE.svg
```

### 3. Mermaid (in README.md)
**Best for:** GitHub/Markdown integration

Already embedded in README.md. GitHub automatically renders mermaid blocks.

**Standalone Render:**
```bash
# Install Mermaid CLI:
npm install -g @mermaid-js/mermaid-cli

# Extract mermaid block from README.md and render:
mmdc -i workflow.mmd -o workflow.png
```

---

## 🎨 Recommended Workflow

1. **For Documentation:** Use Mermaid (already in README.md)
2. **For Presentations:** Use D2 (clean, modern output)
3. **For Enterprise/Detailed:** Use PlantUML (comprehensive)

---

## 🖼️ Preview

### PlantUML Features:
- ✅ Queue shapes (horizontal cylinders)
- ✅ Worker grouping by replica count
- ✅ Top-to-bottom flow
- ✅ Storage hierarchy
- ✅ Notes and annotations

### D2 Features:
- ✅ Modern, clean rendering
- ✅ Automatic layout optimization
- ✅ Queue shapes
- ✅ Nested components
- ✅ Markdown notes

---

## 🔧 Quick Setup

**PlantUML (VS Code):**
```bash
# Install extension
code --install-extension jebbs.plantuml

# Open ARCHITECTURE.puml
# Press Alt+D (or Cmd+D on Mac) to preview
```

**D2 (CLI):**
```bash
# macOS
brew install d2

# Linux
curl -fsSL https://d2lang.com/install.sh | sh -s --

# Render
d2 ARCHITECTURE.d2 output.svg
```

---

## 📦 Output Examples

After rendering, you'll get:
- `ARCHITECTURE.png` (from PlantUML)
- `ARCHITECTURE.svg` (from D2)
- Inline preview in README.md (Mermaid)

All diagrams show the same architecture with different styling/tooling.
