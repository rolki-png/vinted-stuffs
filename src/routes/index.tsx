import { createFileRoute } from '@tanstack/react-router'
import { DealDesk } from '#/components/DealDesk'

export const Route = createFileRoute('/')({
  component: DealDesk,
})
