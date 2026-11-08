import { ReactFlow, Background, Controls, MarkerType, Position } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { TONE } from '../status'

// One diagram per system, built only from network.json. `status` (from buildStatus) colors each node.
function NetworkMap({ system, status = {} }) {
  const nodes = []
  const edges = []

  function addNode(id, kind, x, y) {
    const info = status[id] ?? { tone: 'idle', detail: '' }
    const tone = TONE[info.tone] ?? TONE.idle
    nodes.push({
      id,
      position: { x, y },
      data: {
        label: (
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 11, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 1 }}>{kind}</div>
            <div style={{ fontWeight: 600 }}>{id}</div>
            {info.detail && <div style={{ fontSize: 12, marginTop: 2 }}>{info.detail}</div>}
          </div>
        ),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        background: tone.bg,
        color: tone.text,
        border: `2px solid ${tone.border}`,
        borderRadius: 10,
        width: 190,
        padding: 10,
      },
    })
  }

  function connect(source, target) {
    edges.push({
      id: `${source}->${target}`,
      source,
      target,
      type: 'smoothstep',
      style: { stroke: '#22d3ee', strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#22d3ee' },
    })
  }

  // Give each facility enough vertical room for its wells.
  let nextY = 0
  const facilityCenters = []

  system.facilities.forEach((facility) => {
    const rowHeight = Math.max(facility.wells.length, 1) * 100
    const centerY = nextY + (rowHeight - 100) / 2
    facilityCenters.push(centerY)

    facility.wells.forEach((well, index) => {
      addNode(well.id, 'Well', 0, nextY + index * 100)
      connect(well.id, facility.tank.id)
    })

    addNode(facility.tank.id, 'Tank', 260, centerY)
    addNode(facility.pump.id, 'Pump', 520, centerY)
    addNode(facility.pipeline.id, 'Pipeline', 780, centerY)

    connect(facility.tank.id, facility.pump.id)
    connect(facility.pump.id, facility.pipeline.id)
    connect(facility.pipeline.id, system.disposal_site.id)

    nextY += rowHeight + 100
  })

  const disposalY = facilityCenters.length
    ? (facilityCenters[0] + facilityCenters[facilityCenters.length - 1]) / 2
    : 0
  addNode(system.disposal_site.id, 'Disposal site', 1040, disposalY)

  return (
    <div className="mt-6 h-[600px] overflow-hidden rounded-xl border border-slate-800">
      <ReactFlow
        key={system.id}
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.1}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        colorMode="dark"
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export default NetworkMap
