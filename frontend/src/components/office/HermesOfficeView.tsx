import { Box, Maximize2, Wifi } from 'lucide-react'

export function HermesOfficeView() {
  return (
    <section className="hermes-office-view">
      <div className="hermes-office-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /><Box size={13} /> HERMES3D · AGENTHQ LOCAL STUDIO</div>
          <h1>Live Office</h1>
          <p>Your AgentHQ team inside the immersive 3D office. The office is embedded in this workspace and uses the AgentHQ local runtime.</p>
        </div>
        <div className="hermes-office-actions">
          <span className="hermes-embedded-pill"><span className="live-dot" /> Embedded in AgentHQ</span>
          <a className="secondary-button hermes-fullscreen-link" href="/office" target="_blank" rel="noreferrer">
            <Maximize2 size={15} /> Open full screen
          </a>
        </div>
      </div>

      <div className="hermes-office-frame">
        <iframe
          src="/office"
          title="Hermes3D AgentHQ live office"
          allow="microphone; clipboard-read; clipboard-write"
          allowFullScreen
        />
      </div>

      <div className="hermes-office-footnote">
        <Wifi size={14} />
        <span>Hermes3D is served through AgentHQ's local workspace. Keep the Hermes3D service running in the background; you do not need a separate browser tab.</span>
      </div>
    </section>
  )
}
