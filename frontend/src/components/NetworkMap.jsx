import { useEffect, useRef } from 'react'
import { ReactFlow, Background, Controls, MarkerType, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import Icon from './Icon'
import { TONE } from '../status'
import { C } from '../theme'

const ICON = { Well: 'drop', Tank: 'tank', Pump: 'pump', Pipeline: 'pipe', 'Disposal site': 'disposal' }
const COL = 236 // horizontal distance between columns
const ROW = 72 // vertical distance between wells
const GAP = 36 // extra space between facilities
const NODE_W = 204
const FIT = { padding: 0.06 }

// One diagram per system, built only from network.json. `status` (from buildStatus) colors each node.
function NetworkMap({ system, status = {} }) {
  const boxRef = useRef(null)
  const flowRef = useRef(null)
  // Re-fit when the panel changes width (layout settling, window resize), so nothing is cut off.
  useEffect(() => {
    const box = boxRef.current
    if (!box || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => flowRef.current?.fitView(FIT))
    ro.observe(box)
    return () => ro.disconnect()
  }, [])

  const nodes = []
  const edges = []

  function addNode(id, kind, x, y) {
    const info = status[id] ?? { tone: 'idle', detail: '' }
    const tone = TONE[info.tone] ?? TONE.idle
    const disposal = kind === 'Disposal site'
    const edge = disposal ? C.brand : tone.border
    nodes.push({
      id,
      position: { x, y },
      className: `ns-node${info.tone === 'bad' ? ' ns-node-bad' : ''}`,
      data: {
        label: (
          <div style={{ textAlign: 'left' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: disposal ? C.brand : tone.border, display: 'flex' }}>
                <Icon name={ICON[kind]} size={16} />
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 600,
                  fontSize: 14,
                  color: C.fg,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {id}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 12, whiteSpace: 'nowrap' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.1em',
                  color: C.muted,
                }}
              >
                {kind}
              </span>
              {info.detail && (
                <span style={{ fontFamily: 'var(--font-mono)', color: info.tone === 'idle' ? C.muted : tone.text, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {info.detail}
                </span>
              )}
            </div>
          </div>
        ),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        background: `color-mix(in srgb, ${edge} ${info.tone === 'idle' && !disposal ? 0 : 9}%, ${C.surface})`,
        color: C.fg,
        border: `1px solid ${edge}`,
        borderLeft: `3px solid ${edge}`,
        borderRadius: 4,
        width: disposal ? NODE_W + 48 : NODE_W,
        padding: '8px 10px',
      },
    })
  }

  function connect(source, target) {
    edges.push({
      id: `${source}->${target}`,
      source,
      target,
      type: 'smoothstep',
      style: { stroke: C.data, strokeWidth: 1.5, strokeOpacity: 0.45 },
      markerEnd: { type: MarkerType.ArrowClosed, color: C.data, width: 16, height: 16 },
    })
  }

  // Give each facility enough vertical room for its wells.
  let nextY = 0
  const facilityCenters = []

  system.facilities.forEach((facility) => {
    const rowHeight = Math.max(facility.wells.length, 1) * ROW
    const centerY = nextY + (rowHeight - ROW) / 2
    facilityCenters.push(centerY)

    facility.wells.forEach((well, index) => {
      addNode(well.id, 'Well', 0, nextY + index * ROW)
      connect(well.id, facility.tank.id)
    })

    addNode(facility.tank.id, 'Tank', COL, centerY)
    addNode(facility.pump.id, 'Pump', COL * 2, centerY)
    addNode(facility.pipeline.id, 'Pipeline', COL * 3, centerY)

    connect(facility.tank.id, facility.pump.id)
    connect(facility.pump.id, facility.pipeline.id)
    connect(facility.pipeline.id, system.disposal_site.id)

    nextY += rowHeight + GAP
  })

  const disposalY = facilityCenters.length
    ? (facilityCenters[0] + facilityCenters[facilityCenters.length - 1]) / 2
    : 0
  addNode(system.disposal_site.id, 'Disposal site', COL * 4, disposalY)

  return (
    <div ref={boxRef} className="ns-map screen mt-4 h-[600px] overflow-hidden">
      <ReactFlow
        key={system.id}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={FIT}
        onInit={(instance) => {
          flowRef.current = instance
          requestAnimationFrame(() => instance.fitView(FIT))
        }}
        minZoom={0.1}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        colorMode="dark"
        attributionPosition="top-right"
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  )
}

export default NetworkMap
