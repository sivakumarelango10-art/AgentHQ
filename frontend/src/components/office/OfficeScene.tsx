import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { ContactShadows, Html, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import type { Agent } from '../../types'

type Props = {
  agents: Agent[]
  selectedAgentId: string
  onSelectAgent: (id: string) => void
  cameraMode: 'orbit' | 'overview'
}

const employeePositions: Record<string, [number, number, number]> = {
  ceo: [-7.6, 0.05, -2.9],
  pm: [-4.7, 0.05, 0.05],
  dev: [-1.6, 0.05, 0.05],
  design: [-7.65, 0.05, 3.15],
  research: [4.7, 0.05, 0.05],
  qa: [0.55, 0.05, 3.02],
}

function Desk({ position, width = 2.35 }: { position: [number, number, number]; width?: number }) {
  return (
    <group position={position}>
      <mesh position={[0, 1.02, 0]} castShadow receiveShadow>
        <boxGeometry args={[width, 0.12, 1.15]} />
        <meshStandardMaterial color="#806b55" roughness={0.55} />
      </mesh>
      {[-width / 2 + 0.12, width / 2 - 0.12].map((x) => <mesh key={x} position={[x, 0.48, 0]} castShadow>
        <boxGeometry args={[0.1, 0.96, 0.95]} />
        <meshStandardMaterial color="#343c39" roughness={0.75} />
      </mesh>)}
      <mesh position={[0, 1.12, -0.05]} castShadow>
        <boxGeometry args={[0.62, 0.045, 0.4]} />
        <meshStandardMaterial color="#1a211f" metalness={0.25} roughness={0.35} />
      </mesh>
      <mesh position={[0, 1.48, -0.24]} castShadow>
        <boxGeometry args={[0.74, 0.48, 0.075]} />
        <meshStandardMaterial color="#171e1d" metalness={0.35} roughness={0.25} />
      </mesh>
      <mesh position={[0, 1.48, -0.198]}>
        <planeGeometry args={[0.65, 0.37]} />
        <meshStandardMaterial color="#9cb9b0" emissive="#34584e" emissiveIntensity={0.32} roughness={0.35} />
      </mesh>
      <mesh position={[0, 1.14, 0.34]}>
        <boxGeometry args={[0.68, 0.035, 0.22]} />
        <meshStandardMaterial color="#202725" roughness={0.55} />
      </mesh>
      <mesh position={[0.78, 1.12, -0.22]}>
        <cylinderGeometry args={[0.07, 0.07, 0.025, 16]} />
        <meshStandardMaterial color="#202725" />
      </mesh>
    </group>
  )
}

function Chair({ position, rotation = 0 }: { position: [number, number, number]; rotation?: number }) {
  return <group position={position} rotation={[0, rotation, 0]}>
    <mesh position={[0, 0.62, 0]} castShadow><boxGeometry args={[0.7, 0.12, 0.68]} /><meshStandardMaterial color="#293431" roughness={0.72} /></mesh>
    <mesh position={[0, 1.03, 0.28]} castShadow><boxGeometry args={[0.7, 0.82, 0.12]} /><meshStandardMaterial color="#303c38" roughness={0.8} /></mesh>
    <mesh position={[0, 0.3, 0]}><cylinderGeometry args={[0.055, 0.055, 0.55, 12]} /><meshStandardMaterial color="#8b938c" metalness={0.65} roughness={0.3} /></mesh>
    <mesh position={[0, 0.07, 0]}><cylinderGeometry args={[0.34, 0.34, 0.07, 20]} /><meshStandardMaterial color="#242d2a" /></mesh>
  </group>
}

function Person({ agent, position, selected, onClick }: { agent: Agent; position: [number, number, number]; selected: boolean; onClick: () => void }) {
  const bodyMaterial = new THREE.MeshStandardMaterial({ color: agent.color, roughness: 0.78 })
  const skinMaterial = new THREE.MeshStandardMaterial({ color: '#c99b7a', roughness: 0.82 })
  return <group position={position} onClick={(event) => { event.stopPropagation(); onClick() }} onPointerOver={() => { document.body.style.cursor = 'pointer' }} onPointerOut={() => { document.body.style.cursor = 'default' }}>
    <mesh position={[0, 1.32, 0]} castShadow material={bodyMaterial}><capsuleGeometry args={[0.24, 0.55, 4, 8]} /></mesh>
    <mesh position={[0, 2.02, -0.02]} castShadow material={skinMaterial}><sphereGeometry args={[0.24, 20, 20]} /></mesh>
    <mesh position={[0, 2.19, -0.035]} castShadow><sphereGeometry args={[0.245, 18, 12, 0, Math.PI * 2, 0, Math.PI * 0.52]} /><meshStandardMaterial color="#33302c" roughness={0.9} /></mesh>
    <mesh position={[-0.34, 1.38, -0.05]} rotation={[0, 0, -0.32]} castShadow material={bodyMaterial}><capsuleGeometry args={[0.085, 0.38, 3, 7]} /></mesh>
    <mesh position={[0.34, 1.38, -0.05]} rotation={[0, 0, 0.32]} castShadow material={bodyMaterial}><capsuleGeometry args={[0.085, 0.38, 3, 7]} /></mesh>
    <mesh position={[-0.16, 0.52, 0.02]} rotation={[0, 0, -0.08]} castShadow><capsuleGeometry args={[0.105, 0.46, 3, 7]} /><meshStandardMaterial color="#303b47" roughness={0.82} /></mesh>
    <mesh position={[0.16, 0.52, 0.02]} rotation={[0, 0, 0.08]} castShadow><capsuleGeometry args={[0.105, 0.46, 3, 7]} /><meshStandardMaterial color="#303b47" roughness={0.82} /></mesh>
    {selected && <mesh position={[0, 2.53, 0]}>
      <sphereGeometry args={[0.085, 14, 14]} />
      <meshBasicMaterial color="#d9bd8b" />
    </mesh>}
    <Html position={[0, 2.62, 0]} center distanceFactor={11} style={{ pointerEvents: 'none' }}>
      <div className={`employee-name-tag ${selected ? 'selected' : ''}`}><span className={`mini-status ${agent.status}`} />{agent.name}</div>
    </Html>
  </group>
}

function Plant({ position }: { position: [number, number, number] }) {
  return <group position={position}>
    <mesh position={[0, 0.32, 0]} castShadow><cylinderGeometry args={[0.29, 0.23, 0.58, 20]} /><meshStandardMaterial color="#8a7662" roughness={0.9} /></mesh>
    {Array.from({ length: 7 }, (_, index) => {
      const angle = (index / 7) * Math.PI * 2
      return <mesh key={index} position={[Math.cos(angle) * 0.22, 0.95 + (index % 3) * 0.12, Math.sin(angle) * 0.22]} rotation={[0.18, angle, -0.25 + (index % 2) * 0.5]} castShadow>
        <coneGeometry args={[0.17, 0.95, 8]} /><meshStandardMaterial color={index % 2 ? '#52745d' : '#66866b'} roughness={0.9} />
      </mesh>
    })}
  </group>
}

function RoomLabel({ children, position }: { children: string; position: [number, number, number] }) {
  return <Html position={position} center distanceFactor={15} style={{ pointerEvents: 'none' }}>
    <div className="room-label">{children}</div>
  </Html>
}

function MeetingArea() {
  return <group position={[1.6, 0, 3.8]}>
    <mesh position={[0, 0.9, 0]} castShadow><boxGeometry args={[3.5, 0.13, 2.0]} /><meshStandardMaterial color="#927d65" roughness={0.55} /></mesh>
    <mesh position={[0, 0.44, 0]}><boxGeometry args={[0.18, 0.88, 0.18]} /><meshStandardMaterial color="#3c4741" /></mesh>
    {[-1.05, 1.05].flatMap((x) => [-0.78, 0.78].map((z) => <group key={`${x}-${z}`} position={[x, 0, z]}>
      <mesh position={[0, 0.48, 0]} castShadow><boxGeometry args={[0.58, 0.1, 0.58]} /><meshStandardMaterial color="#45524b" /></mesh>
      <mesh position={[0, 0.85, 0.22]} castShadow><boxGeometry args={[0.58, 0.7, 0.1]} /><meshStandardMaterial color="#45524b" /></mesh>
      <mesh position={[0, 0.22, 0]}><cylinderGeometry args={[0.045, 0.045, 0.42, 10]} /><meshStandardMaterial color="#7e877f" metalness={0.4} /></mesh>
    </group>))}
  </group>
}

const additionalEmployeeSlots: Record<string, [number, number, number][]> = {
  "ceo office": [
    [-6.1, 0.05, -3.0],
    [-9.1, 0.05, -3.0],
    [-6.1, 0.05, -1.0],
  ],
  "development room": [
    [1.55, 0.05, 0.05],
    [6.4, 0.05, -1.6],
    [6.4, 0.05, 0.2],
    [1.55, 0.05, -4.0],
    [4.7, 0.05, -4.0],
    [6.4, 0.05, -4.0],
  ],
  "design studio": [
    [-9.0, 0.05, 3.15],
    [-9.0, 0.05, 5.0],
    [-6.2, 0.05, 4.8],
  ],
  "research room": [
    [6.7, 0.05, -4.0],
    [8.2, 0.05, -2.0],
    [8.2, 0.05, 0.0],
  ],
  "testing lab": [
    [-3.0, 0.05, 5.5],
    [-0.8, 0.05, 5.5],
    [3.7, 0.05, 5.5],
  ],
  "meeting room": [
    [2.65, 0.05, 3.02],
    [0.55, 0.05, 4.58],
    [2.65, 0.05, 4.58],
  ],
  reception: [
    [-4.8, 0.05, 5.6],
    [-2.4, 0.05, 5.6],
    [0.0, 0.05, 5.6],
  ],
}

const defaultOverflowSlots: [number, number, number][] = [
  [-4.6, 0.05, 5.6],
  [-2.3, 0.05, 5.6],
  [0.0, 0.05, 5.6],
  [2.3, 0.05, 5.6],
  [4.6, 0.05, 5.6],
  [6.9, 0.05, 5.6],
]

function employeePosition(agent: Agent, customRoomIndex: number): [number, number, number] {
  const known = employeePositions[agent.id]
  if (known) return known

  const roomKey = agent.room.trim().toLowerCase()
  const slots = additionalEmployeeSlots[roomKey] ?? defaultOverflowSlots
  const knownSlot = slots[customRoomIndex]
  if (knownSlot) return knownSlot

  const overflowIndex = customRoomIndex - slots.length
  const column = overflowIndex % 6
  const row = Math.floor(overflowIndex / 6)
  return [-5.75 + column * 2.3, 0.05, 6.15 - row * 1.15]
}

function OfficeEnvironment({ agents, selectedAgentId, onSelectAgent }: Pick<Props, 'agents' | 'selectedAgentId' | 'onSelectAgent'>) {
  return <>
    <color attach="background" args={['#d8d6cd']} />
    <fog attach="fog" args={['#d8d6cd', 23, 42]} />
    <ambientLight intensity={1.25} />
    <hemisphereLight args={['#f5f4e9', '#7a8179', 0.8]} />
    <directionalLight position={[-7, 13, 7]} intensity={2.0} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-15} shadow-camera-right={15} shadow-camera-top={15} shadow-camera-bottom={-15} />
    <pointLight position={[1, 4.2, -3]} intensity={32} distance={12} color="#f7e4c5" />

    {/* Floor slab and warm timber inset */}
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.12, 0]} receiveShadow>
      <planeGeometry args={[22, 17]} /><meshStandardMaterial color="#b4b0a5" roughness={0.92} />
    </mesh>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.055, 0]} receiveShadow>
      <planeGeometry args={[18.8, 13.8]} /><meshStandardMaterial color="#aa9276" roughness={0.84} />
    </mesh>
    <gridHelper args={[18.8, 38, '#a78f73', '#bda88e']} position={[0, -0.045, 0]} />

    {/* Back wall and glass side partitions */}
    <mesh position={[0, 1.65, -6.95]} receiveShadow castShadow><boxGeometry args={[22, 3.5, 0.25]} /><meshStandardMaterial color="#e6e5df" roughness={0.88} /></mesh>
    <mesh position={[-10.85, 1.65, 0]} castShadow><boxGeometry args={[0.22, 3.5, 14]} /><meshStandardMaterial color="#d8d9d3" roughness={0.8} /></mesh>
    <mesh position={[10.85, 1.65, 0]} castShadow><boxGeometry args={[0.22, 3.5, 14]} /><meshStandardMaterial color="#d8d9d3" roughness={0.8} /></mesh>
    <mesh position={[-7.5, 1.55, 1.8]}><boxGeometry args={[0.07, 3, 5.1]} /><meshPhysicalMaterial color="#aac2bd" transparent opacity={0.28} roughness={0.12} transmission={0.35} /></mesh>
    <mesh position={[7.5, 1.55, 1.8]}><boxGeometry args={[0.07, 3, 5.1]} /><meshPhysicalMaterial color="#aac2bd" transparent opacity={0.28} roughness={0.12} transmission={0.35} /></mesh>
    <mesh position={[-7.5, 1.55, 1.8]}><boxGeometry args={[0.09, 3.12, 0.09]} /><meshStandardMaterial color="#6e7b75" metalness={0.45} roughness={0.3} /></mesh>
    <mesh position={[7.5, 1.55, 1.8]}><boxGeometry args={[0.09, 3.12, 0.09]} /><meshStandardMaterial color="#6e7b75" metalness={0.45} roughness={0.3} /></mesh>

    {/* Ceiling beams */}
    {[-5.5, -1.8, 1.9, 5.6].map((x) => <mesh key={x} position={[x, 3.34, -0.1]}><boxGeometry args={[0.09, 0.12, 13.3]} /><meshStandardMaterial color="#f0eee6" /></mesh>)}
    {[-4.6, 0, 4.6].map((z) => <group key={z} position={[0, 3.15, z]}>
      <mesh><boxGeometry args={[1.65, 0.06, 0.38]} /><meshStandardMaterial color="#f8f3e7" emissive="#fff0cc" emissiveIntensity={0.28} /></mesh>
    </group>)}

    {/* CEO desk */}
    <group position={[-7.6, 0, -4.35]}>
      <Desk position={[0, 0, 0]} width={2.65} />
      <Chair position={[0, 0, 1.4]} />
      <mesh position={[0, 1.82, -0.68]} castShadow><boxGeometry args={[2.45, 0.9, 0.1]} /><meshStandardMaterial color="#55675f" roughness={0.82} /></mesh>
      <mesh position={[0, 1.82, -0.61]}><planeGeometry args={[2.25, 0.7]} /><meshStandardMaterial color="#d9e2dc" /></mesh>
    </group>

    {/* Developer desks */}
    {[-4.7, -1.6, 1.55, 4.7].map((x) => <group key={x}>
      <Desk position={[x, 0, -1.6]} />
      <Chair position={[x, 0, 0.05]} rotation={0} />
    </group>)}

    {/* Design studio side desk */}
    <group position={[-7.65, 0, 1.7]}>
      <Desk position={[0, 0, 0]} width={2.35} />
      <Chair position={[0, 0, 1.45]} />
      <mesh position={[-0.7, 1.62, -0.25]}><boxGeometry args={[0.55, 0.06, 0.45]} /><meshStandardMaterial color="#c7b7a1" /></mesh>
    </group>

    <MeetingArea />
    <Plant position={[-9.1, 0, -5.8]} />
    <Plant position={[9.2, 0, -5.5]} />
    <Plant position={[-9.3, 0, 5.6]} />
    <Plant position={[9.1, 0, 5.3]} />
    <Plant position={[5.8, 0, 3.7]} />

    <RoomLabel position={[-7.6, 2.75, -4.2]}>CEO OFFICE</RoomLabel>
    <RoomLabel position={[0, 2.8, -5.15]}>ENGINEERING</RoomLabel>
    <RoomLabel position={[-7.5, 2.75, 1.9]}>DESIGN STUDIO</RoomLabel>
    <RoomLabel position={[1.7, 2.65, 4.0]}>MEETING ROOM</RoomLabel>

    {(() => {
      // Keep starter employees at their authored coordinates. New employees
      // receive the next free location in their assigned room, regardless of
      // the department-sorted order returned by the database.
      const customRoomIndexes = new Map<string, number>()
      return agents.map((agent) => {
        const roomKey = agent.room.trim().toLowerCase()
        const customRoomIndex = customRoomIndexes.get(roomKey) ?? 0
        const isStarterEmployee = Boolean(employeePositions[agent.id])
        if (!isStarterEmployee) customRoomIndexes.set(roomKey, customRoomIndex + 1)
        const position = employeePosition(agent, customRoomIndex)
        return <Person key={agent.id} agent={agent} position={position} selected={selectedAgentId === agent.id} onClick={() => onSelectAgent(agent.id)} />
      })
    })()}

    <ContactShadows position={[0, -0.035, 0]} opacity={0.27} scale={22} blur={2.4} far={8} resolution={512} color="#303a34" />
  </>
}

export function OfficeScene({ agents, selectedAgentId, onSelectAgent, cameraMode }: Props) {
  return <Canvas
    shadows
    dpr={[1, 1.5]}
    camera={{ position: cameraMode === 'overview' ? [0, 21, 18] : [17, 14, 17], fov: 39, near: 0.1, far: 80 }}
    gl={{ antialias: true, powerPreference: 'high-performance' }}
  >
    <Suspense fallback={null}>
      <OfficeEnvironment agents={agents} selectedAgentId={selectedAgentId} onSelectAgent={onSelectAgent} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.08} minDistance={10} maxDistance={32} maxPolarAngle={Math.PI / 2.05} target={[0, 0.8, 0]} />
    </Suspense>
  </Canvas>
}
