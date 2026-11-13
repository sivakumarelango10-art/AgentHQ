import type { SVGProps } from 'react'

interface LogoIconProps extends SVGProps<SVGSVGElement> {
  size?: number
}

export function LogoIcon({ size = 28, className, ...props }: LogoIconProps) {
  return (
    <svg
      viewBox="0 0 200 200"
      width={size}
      height={size}
      fill="none"
      aria-hidden="true"
      className={className}
      {...props}
    >
      <polygon
        points="100,20 169.3,60 169.3,140 100,180 30.7,140 30.7,60"
        stroke="#22D3EE"
        strokeWidth="9"
        strokeLinejoin="round"
      />
      <line x1="100" y1="100" x2="100" y2="20" stroke="#22D3EE" strokeWidth="7" strokeLinecap="round" />
      <line x1="100" y1="100" x2="169.3" y2="140" stroke="#22D3EE" strokeWidth="7" strokeLinecap="round" />
      <line x1="100" y1="100" x2="30.7" y2="140" stroke="#22D3EE" strokeWidth="7" strokeLinecap="round" />
      <circle cx="100" cy="20" r="12" fill="#0B1020" stroke="#22D3EE" strokeWidth="7" />
      <circle cx="169.3" cy="140" r="12" fill="#0B1020" stroke="#22D3EE" strokeWidth="7" />
      <circle cx="30.7" cy="140" r="12" fill="#0B1020" stroke="#22D3EE" strokeWidth="7" />
      <circle cx="100" cy="100" r="21" fill="#8B5CF6" />
    </svg>
  )
}

