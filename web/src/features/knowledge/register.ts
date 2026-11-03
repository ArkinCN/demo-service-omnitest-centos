/* 把 /knowledge 的版式挂进注册表。src/features/index.tsx 已冻结，
   这一行 import 由 src/app/KnowledgePage.tsx（本包所有）直接引，
   收尾包若要改挂在 features/index.tsx 上，见本包交付物的跨包请求单。 */
import { registerModulePage } from '../../registry'
import { KnowledgeModule } from './KnowledgeModule'

registerModulePage('knowledge', KnowledgeModule)
