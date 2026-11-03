"""
Agreement service - business logic for agreement management
"""
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlmodel import Session, select, col
from app.models.agreement import Agreement, UserAgreementAcceptance
from app.schemas.agreement import AgreementCreate, AgreementUpdate
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException
from app.core.logger import logger


AGREEMENT_TYPES = ["terms_of_service", "privacy_policy"]


class AgreementService:

    @staticmethod
    def create_agreement(session: Session, admin_id: int, data: AgreementCreate) -> Agreement:
        """Create a new agreement draft"""
        # Check for duplicate (type, version)
        existing = session.exec(
            select(Agreement)
            .where(Agreement.type == data.type, Agreement.version == data.version)
        ).first()
        if existing:
            raise ConflictException(f"Agreement {data.type} version {data.version} already exists")

        agreement = Agreement(
            type=data.type,
            version=data.version,
            title=data.title,
            content=data.content,
            is_published=False,
            created_by=admin_id,
        )
        session.add(agreement)
        session.commit()
        session.refresh(agreement)
        logger.info(f"Agreement draft created: {agreement.type} v{agreement.version} by admin {admin_id}")
        return agreement

    @staticmethod
    def update_agreement(session: Session, agreement_id: int, data: AgreementUpdate) -> Agreement:
        """Update an agreement (draft or published)"""
        agreement = session.get(Agreement, agreement_id)
        if not agreement:
            raise NotFoundException("Agreement not found")

        if data.title is not None:
            agreement.title = data.title
        if data.content is not None:
            agreement.content = data.content
        agreement.updated_at = datetime.now(timezone.utc)

        session.add(agreement)
        session.commit()
        session.refresh(agreement)
        return agreement

    @staticmethod
    def delete_agreement(session: Session, agreement_id: int) -> None:
        """Delete an unpublished agreement draft"""
        agreement = session.get(Agreement, agreement_id)
        if not agreement:
            raise NotFoundException("Agreement not found")
        if agreement.is_published:
            raise BadRequestException("Cannot delete a published agreement")

        session.delete(agreement)
        session.commit()
        logger.info(f"Agreement draft deleted: {agreement.type} v{agreement.version}")

    @staticmethod
    def publish_agreement(session: Session, agreement_id: int) -> Agreement:
        """Publish an agreement"""
        agreement = session.get(Agreement, agreement_id)
        if not agreement:
            raise NotFoundException("Agreement not found")
        if agreement.is_published:
            raise BadRequestException("Agreement is already published")

        agreement.is_published = True
        agreement.published_at = datetime.now(timezone.utc)
        agreement.updated_at = datetime.now(timezone.utc)

        session.add(agreement)
        session.commit()
        session.refresh(agreement)
        logger.info(f"Agreement published: {agreement.type} v{agreement.version}")
        return agreement

    @staticmethod
    def get_agreement(session: Session, agreement_id: int) -> Agreement:
        """Get a single agreement by ID"""
        agreement = session.get(Agreement, agreement_id)
        if not agreement:
            raise NotFoundException("Agreement not found")
        return agreement

    @staticmethod
    def list_agreements(
        session: Session,
        type_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[list[Agreement], int]:
        """List all agreements with optional type filter, paginated"""
        statement = select(Agreement)
        count_statement = select(Agreement)

        if type_filter:
            statement = statement.where(Agreement.type == type_filter)
            count_statement = count_statement.where(Agreement.type == type_filter)

        # Count total
        total = len(session.exec(count_statement).all())

        # Paginated results
        statement = statement.order_by(col(Agreement.created_at).desc())
        statement = statement.offset((page - 1) * page_size).limit(page_size)
        items = session.exec(statement).all()

        return list(items), total

    @staticmethod
    def get_all_latest_published(session: Session) -> list[Agreement]:
        """Get the latest published version for each agreement type"""
        result = []
        for agreement_type in AGREEMENT_TYPES:
            statement = (
                select(Agreement)
                .where(Agreement.type == agreement_type, Agreement.is_published == True)
                .order_by(col(Agreement.published_at).desc())
                .limit(1)
            )
            agreement = session.exec(statement).first()
            if agreement:
                result.append(agreement)
        return result

    @staticmethod
    def get_published_versions(session: Session, agreement_type: str) -> list[Agreement]:
        """Get all published versions of a given agreement type, ordered by published_at desc"""
        statement = (
            select(Agreement)
            .where(Agreement.type == agreement_type, Agreement.is_published == True)
            .order_by(col(Agreement.published_at).desc())
        )
        return list(session.exec(statement).all())

    @staticmethod
    def check_acceptance_needed(session: Session, user_id: int) -> Tuple[bool, bool, list[Agreement]]:
        """Check if user needs to accept any new agreements.
        Returns: (needs_acceptance, is_first_time, pending_agreements)
        """
        latest = AgreementService.get_all_latest_published(session)
        pending = []
        for agreement in latest:
            acceptance = session.exec(
                select(UserAgreementAcceptance)
                .where(
                    UserAgreementAcceptance.user_id == user_id,
                    UserAgreementAcceptance.agreement_id == agreement.id,
                )
            ).first()
            if not acceptance:
                pending.append(agreement)

        # Check if user has ever accepted any agreement
        any_acceptance = session.exec(
            select(UserAgreementAcceptance)
            .where(UserAgreementAcceptance.user_id == user_id)
        ).first()
        is_first_time = any_acceptance is None

        return len(pending) > 0, is_first_time, pending

    @staticmethod
    def accept_agreements(session: Session, user_id: int, agreement_ids: list[int]) -> list[UserAgreementAcceptance]:
        """Record user acceptance of agreements"""
        acceptances = []
        for agreement_id in agreement_ids:
            # Validate agreement exists and is published
            agreement = session.get(Agreement, agreement_id)
            if not agreement:
                raise NotFoundException(f"Agreement {agreement_id} not found")
            if not agreement.is_published:
                raise BadRequestException(f"Agreement {agreement_id} is not published")

            # Skip if already accepted
            existing = session.exec(
                select(UserAgreementAcceptance)
                .where(
                    UserAgreementAcceptance.user_id == user_id,
                    UserAgreementAcceptance.agreement_id == agreement_id,
                )
            ).first()
            if existing:
                acceptances.append(existing)
                continue

            acceptance = UserAgreementAcceptance(
                user_id=user_id,
                agreement_id=agreement_id,
            )
            session.add(acceptance)
            acceptances.append(acceptance)

        session.commit()
        for a in acceptances:
            session.refresh(a)
        logger.info(f"User {user_id} accepted agreements: {agreement_ids}")
        return acceptances

    @staticmethod
    def seed_initial_data(session: Session) -> None:
        """Seed initial Terms of Service and Privacy Policy if table is empty"""
        existing = session.exec(select(Agreement).limit(1)).first()
        if existing:
            return

        now = datetime.now(timezone.utc)

        tos = Agreement(
            type="terms_of_service",
            version="内测版",
            title="用户协议（内测版）",
            content=_INITIAL_TOS_CONTENT,
            is_published=True,
            created_by=None,
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        privacy = Agreement(
            type="privacy_policy",
            version="内测版",
            title="隐私政策（内测版）",
            content=_INITIAL_PRIVACY_CONTENT,
            is_published=True,
            created_by=None,
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(tos)
        session.add(privacy)
        session.commit()
        logger.info("Seeded initial agreement data (ToS + Privacy Policy, 内测版)")


# ==================== Initial Content ====================

_INITIAL_TOS_CONTENT = """\n<h1>用户协议（内测版）</h1><p>版本：内测版<br />发布日期：2026年4月15日<br />生效日期：2026年4月15日</p><p>本《用户协议》（以下简称“本协议”）由您（以下简称“用户”或“您”）与示例科技共同订立，就您参与本公司MotorDebug 平台（以下简称“本平台”）的内测活动及使用相关服务（以下简称“本服务”）所涉及的权利义务作出约定。</p><h3><strong>特别声明：内测版服务</strong></h3><p><strong><strong>本平台当前处于内部测试阶段，尚未正式发布。您参与本次内测系基于本公司邀请或特定授权。您充分理解并确认：</strong></strong></p><p><strong><strong>服务不稳定</strong></strong>：本服务在测试期间可能存在中断、延迟、错误、功能不完善、数据丢失等情况。本公司不保证服务能够持续、稳定、无误地运行。</p><p><strong><strong>功能调整</strong></strong>：本公司保留在不事先通知的情况下，随时修改、增加、暂停或下架本服务的全部或部分功能的权利。</p><p><strong><strong>反馈义务</strong></strong>：您同意在测试过程中，就发现的任何问题、错误或改进建议及时向本公司反馈，以协助我们优化服务。</p><p><strong><strong>数据风险</strong></strong>：由于测试环境的不确定性，您通过本服务提交或生成的数据可能存在丢失或损坏的风险。您应在使用前自行做好必要的数据备份。</p><p><strong><strong>保密义务</strong></strong>：除非本公司事先书面同意，您应对本平台的内测版本、技术细节、界面设计、未公开功能等信息承担保密义务，不得向任何第三方泄露或公开讨论。</p><p><strong><strong>本服务仅供受邀的内部工程师及企业端（B端）客户授权工程师在电机驱动项目开发场景下使用，严禁面向个人消费者（C端）开放或销售。</strong></strong></p><h3><strong>一、定义</strong></h3><p>1.<strong><strong>本平台</strong></strong>：指本公司开发和运营的MotorDebug 平台（内测版）。</p><p>2.<strong><strong>本服务</strong></strong>：指本公司通过本平台向内测用户提供的服务，包括但不限于集成多种通用大模型，为用户提供电机驱动项目开发领域的智能问答、代码生成、参数优化建议、故障诊断等功能。具体服务内容以本平台实际提供的为准。</p><p>3.<strong><strong>用户内容</strong></strong>：指用户在使用本服务过程中输入、上传、提交的任何数据、文本、代码、图片、文件、指令等信息（以下简称“输入内容”），以及本平台根据用户输入内容生成的任何回复、结果、代码、建议、分析等内容（以下简称“输出内容”）。输入内容与输出内容统称为“用户内容”。</p><p>4.<strong><strong>第三方大模型</strong></strong>：指本平台集成的、由第三方提供和运营的通用人工智能大模型。各第三方大模型的具体名称、版本及功能特性以本平台实际接入为准，本公司保留根据业务需要调整、增加或下架第三方大模型的权利。</p><p>5.<strong><strong>企业用户</strong></strong>：指以法人或其他组织名义注册并使用本服务的用户。</p><p>6.<strong><strong>授权工程师</strong></strong>：指经企业用户或本公司内部授权，为进行电机调试、产品研发、运维管理等专业技术工作而使用本平台的特定技术人员。</p><p>7.<strong><strong>个人用户</strong></strong>：鉴于本服务涉及专业工业场景及大模型技术风险，<strong><strong>本平台不面向个人消费者（C端用户）开放注册或使用</strong></strong>。如您以自然人身份注册，仅限本公司内部工程师或经本公司审核的B端客户工程师，且您须承诺使用本服务系基于职务行为。本公司有权拒绝或终止任何不具备相应资质或非属授权范围的自然人账户。</p><h3><strong>二、协议的适用与生效</strong></h3><p>1.<strong><strong>主体资格与使用范围限制</strong></strong>。本平台及本服务<strong><strong>仅供企业用户、本公司内部工程师及B端客户授权工程师在工业电机驱动项目开发场景下使用，严禁任何形式的面向个人消费者（C端）的销售、推广或开放注册。</strong></strong>您确认，您已充分理解本服务的专业性和潜在风险，并承诺仅在职务授权范围内使用本服务。如您不具备本协议约定的主体资格（如您是个人消费者），请立即停止注册或使用行为。因违反本条款导致的一切法律责任（包括但不限于对第三方造成的损失、监管处罚等）由违规使用者及其所属单位自行承担。</p><p>2.<strong><strong>协议的接受与生效</strong></strong>。您在注册页面点击“同意”或“注册”，或以任何方式使用本服务，即表示您已阅读、理解并同意接受本协议的全部内容。本协议自您完成上述操作之日起生效。</p><p>3.<strong><strong>协议的变更</strong></strong>。本公司有权根据测试需要、法律法规变化或业务发展，不时修订本协议。修订后的协议将在本平台公示，一经公布即生效。如您不同意修订后的协议，您应当立即停止使用本服务；如您在修订后的协议生效后继续使用本服务，即视为您已接受修订后的协议。</p><p>4.<strong><strong>补充协议与规则</strong></strong>。本协议内容包括协议正文及本平台已经发布或将来可能发布的各类规则、操作指引、公告、通知等。所有规则为本协议不可分割的组成部分。对于特定功能模块，本公司可能要求您另行同意补充协议。</p><h3><strong>三、账户注册、使用与安全</strong></h3><p>1.<strong><strong>账户注册</strong></strong>。为参与内测并使用本服务，您需要注册一个账户。在注册时，您应当提供真实、准确、完整、有效的身份信息及联系方式（如企业邮箱等），并在相关信息发生变更时及时更新。您不得使用他人身份信息进行注册，不得冒充他人，不得创建虚假账户。<strong><strong>本公司有权基于内测名额限制或身份审核结果，拒绝或暂停任何账户的注册申请。</strong></strong></p><p>2.<strong><strong>账户安全</strong></strong>。您的账户仅限您本人使用。您应对您的账户信息（包括但不限于用户名、密码等）承担保密义务，不得向任何第三方泄露、出借、出租、转让或出售账户。您应对您账户下发生的所有活动承担全部责任。如发现任何未经授权使用您账户的情况，您应立即通知本公司。</p><p>3.<strong><strong>账户管理</strong></strong>。本公司有权根据内测计划、法律法规、监管要求或本协议的约定，自行决定对用户账户采取限制、暂停或终止服务等措施，包括但不限于：用户违反本协议约定；用户提供虚假注册信息；内测活动结束或服务停止运营；应司法机关或行政机关的要求等。</p><p>4.<strong><strong>企业用户特别约定</strong></strong>。如您代表企业或实体注册账户，您声明并保证：您已获得该企业或实体的合法授权；您提供的企业信息真实、准确、完整；该企业或实体同意受本协议约束，并对其员工、代理人或关联方通过该账户使用本服务的一切行为承担全部法律责任。</p><h3><strong>四、服务内容与使用规范</strong></h3><p>1.<strong><strong>服务内容</strong></strong>。本平台集成多种第三方通用大模型，面向电机驱动项目开发领域提供智能问答、参数优化、故障诊断、代码生成等测试性服务。具体功能以本平台实际提供的为准。本公司保留根据测试反馈调整、变更或下架部分服务的权利，恕不另行通知。</p><p>2.<strong><strong>关于第三方大模型的重要声明</strong></strong>。本平台通过API等方式调用第三方提供的大模型能力向用户提供服务。<strong><strong>用户知悉并同意：</strong></strong></p><p>（1）本平台调用的第三方大模型由第三方独立提供和运营，本公司不对任何第三方大模型的技术性能、服务质量、安全性、可用性、准确性、可靠性、合法性等作出任何明示或默示的保证。用户使用特定第三方大模型所产生的任何风险由用户自行承担。</p><p>（2）用户在使用本服务过程中选择调用不同的第三方大模型，其输入内容将被传输至相应的第三方大模型服务提供商进行处理。不同第三方大模型对用户数据的处理方式、保留期限、是否用于模型训练等政策可能存在差异，<strong><strong>用户在使用特定第三方大模型前，应自行查阅并了解该第三方大模型的相关服务协议和隐私政策。</strong></strong></p><p>（3）本公司不保证所有第三方大模型均能持续可用。如因第三方原因导致某一或某些大模型无法正常提供服务，但不因此承担违约责任。</p><p>3.<strong><strong>第三方软件依赖与合规使用。</strong></strong></p><p>（1）<strong><strong>第三方软件声明</strong></strong>。本平台的部分功能（包括但不限于代码编译、构建、调试等）<strong><strong>依赖您在本地电脑上自行安装的特定第三方软件</strong></strong>（包括但不限于Keil MDK集成开发环境，以下简称“第三方软件”）。<strong><strong>本平台不提供、不包含、不分发任何第三方软件的安装程序、代码、组件或破解补丁。</strong></strong>如您需要使用本平台的相关功能，您应自行从第三方软件的官方渠道获取并安装合法授权的版本。</p><p>（2）<strong><strong>技术实现说明</strong></strong>。您知悉并同意，为实现本平台与第三方软件的交互，本平台的客户端程序或脚本可能会在您的操作系统环境中执行以下操作：（1）查找第三方软件的安装路径（通过注册表、环境变量或预设目录）；（2）以命令行方式调用第三方软件的可执行文件，并传递必要的参数（如工程文件路径、编译选项等）。<strong><strong>上述操作仅限于进程间调用，不涉及对第三方软件目标代码的复制、修改、反向工程或破解授权验证机制。</strong></strong></p><p>4.<strong><strong>输出内容的性质</strong></strong>。用户理解并确认，本服务基于人工智能技术生成输出内容，且<strong><strong>当前处于内测阶段，算法与模型仍在持续优化中，输出内容可能存在错误、偏差或不完整。输出内容仅供专业工程师在测试环境中参考，严禁直接用于实际生产环境、设备控制或安全关键决策。</strong></strong>对于涉及电机运行安全、生产安全、人身财产安全的重要决策，用户应自行审慎评估，或咨询具备相应资质的专业机构和人员。用户因依赖输出内容而产生的任何损失，本公司不承担法律责任。</p><p>5.<strong><strong>使用场景限制与高风险场景特别警告</strong></strong>。</p><p>（1）用户知悉并确认，本平台作为面向B端工业领域的辅助测试工具，其生成的输出内容<strong><strong>仅供授权工程师在专业工作流程中参考，严禁直接用于生产线联动、安全防护装置触发等高风险自动化闭环场景。</strong></strong></p><p>（2）若用户将本平台的输出内容（如参数建议、代码片段）应用于实际电机驱动或生产环境，<strong><strong>用户必须在实施前经过严格的仿真测试、人工复核及安全校验。</strong></strong>任何因越过人工审核环节直接应用AI生成内容导致的设备损坏、生产中断、人员伤亡、数据丢失或其他财产损失，本公司不承担任何直接或间接责任。</p><p>（3）用户进一步承诺，不会将本服务作为面向C端消费者的终端产品的一部分（如家用电器内置AI、消费级APP等）进行转售或开放。</p><p>6.<strong><strong>使用规范</strong></strong>。用户在使用本服务时，应遵守中华人民共和国法律法规、社会公德和公序良俗，不得利用本服务从事以下行为：</p><p>（1）违反法律法规，危害国家安全、荣誉和利益，泄露国家秘密，颠覆国家政权，破坏国家统一，煽动民族仇恨、民族歧视，破坏民族团结，破坏国家宗教政策，宣扬邪教和封建迷信；</p><p>（2）传播或生成含有暴力、恐怖、淫秽、色情、赌博、毒品、犯罪、侵权、虚假信息等违法违规内容的输入或输出内容；</p><p>（3）侵犯他人合法权益，包括但不限于知识产权、商业秘密、名誉权、肖像权、隐私权、个人信息权益等；</p><p>（4）输入或生成涉及他人敏感个人信息（如身份证号码、银行账户、健康信息、行踪轨迹等）的内容，除非已依法取得信息主体的单独同意；</p><p>（5）利用本服务从事任何可能干扰、破坏、限制或损害本平台正常运行的行为，包括但不限于：对服务器进行攻击或恶意访问；利用技术手段绕过或破坏本平台的安全措施；反向工程、反编译、反汇编或以其他方式试图获取本平台的源代码、算法或核心技术信息；未经授权批量调用API接口等；</p><p>（6）利用本服务开发、训练或优化与本平台存在竞争关系的AI模型或服务；</p><p>（7）未经本公司书面许可，擅自将本服务（包括API接口）转售、再许可或以其他方式提供给第三方使用；</p><p>（8）其他违反法律法规、社会公共利益或本协议约定的行为。</p><p>7.<strong><strong>用户承诺</strong></strong>。用户承诺对其输入内容及通过本服务生成的输出内容自行承担全部责任。如因用户内容违反法律法规或侵犯第三方合法权益而引起的任何索赔、诉讼、损失、费用，由用户自行承担；如因此给本公司造成损失的，用户应予赔偿。</p><h3><strong>五、知识产权</strong></h3><p>1.<strong><strong>本平台及本公司的知识产权</strong></strong>。本平台（包括但不限于平台本身的代码、软件、界面设计、商标、标识、Logo、文档、技术方案等）以及<strong><strong>本公司向用户提供的、用于在本平台进行测试的电机代码、参数模板、算法库、示例数据集及其他技术资料（以下统称“本公司代码”）</strong></strong> 的知识产权归本公司或其许可方所有，受中华人民共和国著作权法、商标法、专利法、反不正当竞争法及相关国际条约的保护。</p><p>2.<strong><strong>本公司代码的使用授权与限制</strong></strong>。</p><ol><li><strong><strong>有限授权</strong></strong>。为使用本服务进行电机调试测试，本公司授予用户一项<strong><strong>有限、非独占、不可转让、不可再许可、不可分许可、可随时撤销的免费使用权</strong></strong>，授权用户仅可在本平台提供的测试环境内，通过本平台提供的功能界面对本公司代码进行上传、运行、查看结果及必要的修改（仅限于平台功能允许的目的）。</li></ol><p>用户知悉并同意，在使用本服务过程中，本平台基于<strong><strong>本公司代码</strong></strong>及用户输入的调试指令、参数配置等信息，经第三方大模型处理后生成的任何输出内容（包括但不限于修改后的代码片段、调试建议、性能分析报告、参数优化方案等），<strong><strong>均系在本公司代码基础上通过自动化技术生成的衍生成果。</strong></strong></p><p>（2）<strong><strong>严格禁止行为</strong></strong>。用户确认并承诺，在使用本服务过程中及服务终止后：</p><ul><li><strong><strong>不得</strong></strong>以任何方式对本公司代码的全部或部分进行复制、下载、存储、分发、出租、出借、出售、转让、公开传播或通过其他任何途径提供给任何第三方；</li><li><strong><strong>不得</strong></strong>对本公司代码进行反向工程、反编译、反汇编，或试图提取本公司代码的源代码、算法、设计思路或核心技术信息；</li><li><strong><strong>不得</strong></strong>利用本公司代码或其衍生成果开发、训练或优化任何与本公司存在竞争关系或可能替代本服务的AI模型、软件或服务；</li><li><strong><strong>不得</strong></strong>将本公司代码用于除在本平台进行测试评估之外的任何商业或非商业目的。</li></ul><p>（3）<strong><strong>保密义务</strong></strong>。用户应将本公司代码视为本公司的商业秘密，采取不低于保护自身同类商业秘密的审慎程度予以保密。未经本公司书面同意，不得向任何第三方披露本公司代码的任何内容。本保密义务在本协议终止后持续有效。</p><p>3.输入/输出内容的<strong><strong>知识产权</strong></strong>。</p><p>（1）在用户和本公司之间，在适用法律允许的范围内，用户提供的输入的知识产权可能归属于你或者依法享有这些知识产权的权利人。</p><p>（2）如果输入和/或输出本身包含了本公司享有知识产权或其他合法权益的内容，则前述输入和/或输出的相应权利仍由本公司享有，不因包含在输出当中而改变其权属。</p><p>（3）用户进一步知悉并同意，基于人工智能技术生成的内容，在现行法律框架下其知识产权归属仍存在一定争议，用户应自行关注相关法律法规的变化，并自行承担因使用输出内容而可能产生的知识产权风险。</p><p>4.<strong><strong>第三方大模型的知识产权提示</strong></strong>。本服务生成的输出内容系通过调用第三方大模型API生成。不同第三方大模型对输出内容的知识产权主张可能存在差异。<strong><strong>本公司不对任何第三方大模型可能就输出内容主张的知识产权权利承担任何责任。</strong></strong>用户在使用输出内容前，应自行查阅并遵守相应第三方大模型的服务协议和知识产权政策。</p><p>5.<strong><strong>侵权责任</strong></strong>。如用户违反本协议的任何约定，导致第三方就本公司代码或输出内容向本公司提出知识产权侵权主张，用户应承担由此给本公司造成的全部损失（包括但不限于赔偿金、和解金、诉讼费、律师费、商誉损失等），并应积极配合本公司采取法律行动维护权益。</p><p>6.<strong><strong>反馈与建议</strong></strong>。用户在内测期间向本公司提供的任何反馈、意见、建议、改进方案等，视为用户同意本公司可不受限制地使用、修改、实施该等内容，无需向用户支付任何报酬或承担任何义务。</p><h3><strong>六、收费与支付</strong></h3><p><strong><strong>1.</strong></strong>当前内测阶段，本服务暂时免费向受邀用户提供。未来正式上线后的收费政策将另行通知。本公司保留在未来任何时间引入收费模式的权利。</p><h3><strong>七、免责声明与责任限制</strong></h3><p>1.<strong><strong>服务“按现状”提供</strong></strong>。本服务按“现状”和“可提供”状态提供，且<strong><strong>当前为内测版本，尚未达到正式发布标准。</strong></strong> 在法律允许的最大范围内，本公司不对本服务作出任何明示或默示的保证，包括但不限于：本服务不会中断、及时、安全、无误；本服务能够满足用户的特定需求或预期；输出内容的准确性、完整性、可靠性、合法性、实用性；第三方大模型的可用性和服务质量；通过本服务获取的任何信息的准确性等。</p><p>2.<strong><strong>内测阶段特别免责</strong></strong>。用户充分知悉并接受内测阶段存在的各项风险，包括但不限于服务中断、数据丢失、功能异常、输出错误、安全漏洞等。用户参与内测系自愿行为，<strong><strong>因内测服务造成的任何直接或间接损失，本公司不承担赔偿责任。</strong></strong></p><p>3.<strong><strong>第三方服务免责</strong></strong>。本平台调用的第三方大模型由第三方独立提供和运营。本公司对第三方大模型的服务质量、安全性、数据保护措施、合规性等不作任何保证。因第三方大模型的服务中断、数据泄露、内容违规等问题给用户造成的任何损失，本公司不承担责任。</p><p>4.<strong><strong>用户自身责任</strong></strong>。用户应对其使用本服务的行为及其输入内容承担全部责任。用户应自行采取合理措施备份其输入内容和输出内容，本公司不对用户内容的丢失、损坏或删除承担责任。</p><p>5.<strong><strong>B端用户特别免责声明</strong></strong>。鉴于本服务的B端专业属性及内测性质，用户确认其具备独立评估输出内容专业性和准确性的能力。对于因用户单方面依赖输出内容、违反使用场景限制或未履行内部审批流程所造成的任何损失，<strong><strong>在法律允许的最大范围内，本公司不承担任何责任。</strong></strong></p><p>6.<strong><strong>责任限制</strong></strong>。在适用法律允许的最大范围内，对于因本协议或本服务引起的或与之相关的任何直接损失、间接损失、附带损失、特殊损失、惩罚性赔偿或后果性损失（包括但不限于利润损失、数据丢失、商誉损失、业务中断损失等），本公司均不承担责任。</p><p>7.<strong><strong>赔偿</strong></strong>。如因用户违反本协议（包括但不限于将账户共享给非授权个人、向C端市场转售本服务接口等）导致本公司遭受任何第三方索赔、行政处罚或声誉损失的，用户应赔偿本公司因此遭受的全部损失（包括合理的律师费、诉讼费、和解金等）。</p><h3><strong>八、隐私保护与数据安全</strong></h3><p>1.<strong><strong>隐私政策</strong></strong>。本公司重视用户隐私和个人信息的保护。用户使用本服务所涉及的个人信息收集、使用、存储、共享、跨境传输等事项，适用本公司另行发布的《隐私政策（内测版）》。用户在使用本服务前，应仔细阅读并理解《隐私政策（内测版）》的全部内容。《隐私政策（内测版）》构成本协议不可分割的组成部分。</p><p>2.<strong><strong>数据安全</strong></strong>。本公司将采取符合行业标准的安全技术措施和管理措施，保护用户数据的安全性和保密性。但鉴于内测阶段系统的不稳定性，用户应自行承担数据安全风险。</p><h3><strong>九、协议的终止</strong></h3><p>1.<strong><strong>用户终止</strong></strong>。用户可以随时通过注销账户的方式终止本协议。账户注销后，本公司将按照《隐私政策（内测版）》的规定处理用户的相关数据。</p><p>2.<strong><strong>本公司终止</strong></strong>。如发生以下情形，本公司有权在不事先通知用户的情况下，暂停或终止向用户提供本服务的全部或部分，并终止本协议：</p><p>（1）用户违反本协议的任何约定；<br />（2）用户提供虚假注册信息或从事违法、违规行为；<br />（3）内测结束，本平台停止运营或转为正式版；<br />（4）根据法律法规、监管要求或司法机关的指令；<br />（5）本公司根据业务调整需要决定停止运营本平台。</p><p>3.<strong><strong>终止后的处理</strong></strong>。本协议终止后，用户在本平台的账户将同时被注销，用户将无法继续使用本服务。本公司没有义务向用户保留或提供用户账户中的任何用户内容。本协议中按其性质应当在协议终止后继续有效的条款继续有效。</p><h3><strong>十、法律适用与争议解决</strong></h3><p>1.<strong><strong>法律适用</strong></strong>。本协议的订立、履行、解释及争议的解决均适用中华人民共和国法律。</p><p>2.<strong><strong>争议解决</strong></strong>。因本协议引起或与本协议有关的任何争议，双方应首先通过友好协商解决。协商不成的，任何一方均可将争议提交至<strong><strong>【本公司住所地】有管辖权的人民法院诉讼解决</strong></strong>。</p><h3><strong>十一、一般条款</strong></h3><p>1.<strong><strong>通知与送达</strong></strong>。本公司向用户发出的通知，可以通过本平台公告、站内信、电子邮件、短信等方式送达。</p><p>2.<strong><strong>可分割性</strong></strong>。如本协议的任何条款被认定为无效或不可执行，不影响本协议其他条款的效力和执行。</p><p>3.<strong><strong>不弃权</strong></strong>。本公司未行使或延迟行使本协议项下的任何权利，不构成对该权利的放弃。</p><p>4.<strong><strong>协议转让</strong></strong>。未经本公司事先书面同意，用户不得将本协议项下的权利和义务转让给任何第三方。本公司有权在合并、收购、资产转让等情况下，将本协议项下的权利和义务转让给关联公司或第三方。</p><p>5.<strong><strong>完整协议</strong></strong>。本协议连同《隐私政策（内测版）》及相关规则，构成双方就本服务事项达成的完整协议。</p><p>6.<strong><strong>联系方式</strong></strong>。如您对本协议有任何疑问、意见或建议，请通过电子邮箱：docs@example.internal与我们联系。</p>
"""

_INITIAL_PRIVACY_CONTENT = """\n<h1>隐私政策（内测版）</h1><p>版本：内测版<br />发布日期：2026年4月15日<br />生效日期：2026年4月15日</p><h2><strong>隐私政策（内测版）</strong></h2><p>本《隐私政策》（内测版）（以下简称“本政策”）由您（以下简称“用户”或“您”）与示例科技（以下简称“本公司”或“我们”）共同订立。我们非常重视您的个人信息和隐私保护。本政策旨在向您说明，在您参与本公司MotorDebug 平台（以下简称“本平台”）内测活动及使用相关服务（以下简称“本服务”）时，我们如何收集、使用、存储、共享、跨境传输和保护您的数据和个人信息，以及您所享有的相关权利。</p><h3><strong>特别声明：内测版服务</strong></h3><p><strong><strong>本平台当前处于内部测试阶段，尚未正式发布。您参与本次内测系基于本公司邀请或特定授权。您充分理解并确认：</strong></strong></p><p><strong><strong>数据处理的测试性质</strong></strong>：在内测期间，我们对个人信息的处理流程、安全措施、存储期限等可能根据测试需要进行调整。我们将尽合理努力保护您的个人信息安全，但由于测试环境的不稳定性，无法保证达到正式版同等级别的保护水平。</p><p><strong><strong>用户内容用于优化</strong></strong>：在内测期间，我们可能会收集和使用您的反馈信息、使用数据以及脱敏后的用户内容，用于分析、改进和优化本平台的性能与服务。</p><p><strong><strong>功能与政策的变更</strong></strong>：我们可能随时调整本平台的功能或修改本政策，恕不另行单独通知。您应定期查阅本政策以了解变更。</p><p><strong><strong>本服务仅供受邀的内部工程师及企业端（B端）客户授权工程师在专业电机驱动项目开发场景下使用，严禁面向个人消费者（C端）开放或销售。</strong></strong></p><h3><strong>一、定义</strong></h3><p>1.<strong><strong>个人信息</strong></strong>：指以电子或者其他方式记录的与已识别或者可识别的自然人有关的各种信息，不包括匿名化处理后的信息。</p><p>2.<strong><strong>敏感个人信息</strong></strong>：指一旦泄露或者非法使用，容易导致自然人的人格尊严受到侵害或者人身、财产安全受到危害的个人信息。</p><p>3.<strong><strong>用户内容</strong></strong>：指用户在使用本服务过程中输入、上传、提交的任何数据、文本、代码、图片、文件、指令等信息（“输入内容”），以及本平台根据用户输入内容生成的任何回复、结果、代码、建议、分析等内容（“输出内容”）。</p><p>4.<strong><strong>第三方大模型</strong></strong>：指本平台集成的、由第三方提供和运营的通用人工智能大模型。</p><p>5.<strong><strong>授权工程师</strong></strong>：指经企业用户或本公司内部授权，为进行专业工作而使用本平台的特定技术人员。</p><h3><strong>二、本政策的适用范围</strong></h3><p>1.本政策适用于您通过本平台访问和使用本服务时，我们收集和处理的您的个人信息。</p><p>2.<strong><strong>特别提示——第三方大模型</strong></strong>。本平台通过API等方式集成了多家第三方通用大模型。当您使用本服务并选择调用特定的第三方大模型时，您的输入内容将被传输至该第三方大模型进行处理。<strong><strong>第三方大模型对您的输入内容的收集、使用、存储、处理方式及其隐私保护措施，适用该第三方的隐私政策，而不适用本政策。</strong></strong></p><p>3.<strong><strong>非C端声明</strong></strong>。<strong><strong>本平台仅为B端业务及内部研发设计，不面向个人消费者提供服务。</strong></strong>如您是个人消费者，请勿使用本平台。对于企业用户或授权工程师，您理解并同意，您在使用过程中提供的联系方式、身份信息以及输入内容，将被视为基于职务行为的必要信息。</p><h3><strong>三、我们如何收集和使用您的个人信息</strong></h3><p><strong><strong>（一）您主动提供的信息</strong></strong></p><p>1.<strong><strong>账户注册信息</strong></strong>。当您注册本平台账户时，我们会收集您的电子邮箱、用户名、密码等信息。我们可能优先要求您使用企业邮箱注册，以验证您的内测资格。</p><p>2.<strong><strong>身份认证信息</strong></strong>。根据内测审核要求或为向您提供特定服务，我们可能需要收集您的身份认证信息，包括但不限于姓名、企业名称等。</p><p>3.<strong><strong>用户内容中的个人信息</strong></strong>。当您使用本服务时，您在输入内容中可能包含个人信息。<strong><strong>我们特别提醒您，本平台系面向电机驱动项目开发专业场景，严禁输入与工作无关的敏感个人信息或与工业场景无关的C端消费者个人数据。</strong></strong>如因您违反职务场景限制输入C端消费者数据导致的合规风险，由您及您所属的企业用户自行承担。</p><p>4.<strong><strong>客服与通信信息</strong></strong>。当您通过客服渠道与我们联系时，我们会收集您的联系方式及沟通内容。</p><p>5.<strong><strong>反馈信息</strong></strong>。当您对本服务的输出内容进行评价或提供其他反馈时，我们会收集相关反馈内容和关联的用户内容。</p><p><strong><strong>（二）我们自动收集的信息</strong></strong></p><p>1.在您访问和使用本平台的过程中，我们可能会自动收集以下信息：</p><p>（1）<strong><strong>设备信息</strong></strong>：包括设备型号、操作系统及版本、设备标识符及版本等；<br />（2）<strong><strong>日志信息</strong></strong>：包括您的IP地址、访问时间、访问页面、操作记录、服务使用情况、性能数据等；<br />（3）<strong><strong>使用信息</strong></strong>：包括您使用本服务的频率、时长、调用的模型类型、使用量等统计信息。</p><p><strong><strong>（三）信息使用的目的与法律基础</strong></strong></p><p>1.我们收集和使用您的个人信息，主要用于以下目的：</p><p>（1）<strong><strong>提供和测试本服务</strong></strong>：创建和管理账户、验证身份、处理请求和指令、生成输出内容、提供客户支持、分析测试数据以改善和优化服务质量等；<br />（2）<strong><strong>履行法定义务</strong></strong>：遵守法律法规的要求、配合监管和司法调查等；<br />（3）<strong><strong>安全保障</strong></strong>：保障本平台及服务的安全稳定运行，检测、预防和应对安全事件、欺诈或滥用行为；<br />（4）<strong><strong>服务改进与分析</strong></strong>：对内测期间的服务使用情况进行统计、分析，以改进产品和服务（在此过程中我们会尽可能使用匿名化或去标识化处理后的数据）。</p><p>2.我们处理个人信息的法律基础包括：您的同意、履行合同所必需、履行法定义务所必需以及基于我们的合法利益。</p><h3><strong>四、关于用户内容处理方式的重要说明</strong></h3><p>1.本平台作为大模型集成平台，用户内容的处理方式如下：</p><p>（1）<strong><strong>传输至第三方大模型</strong></strong>：当您使用本服务时，您的输入内容将被传输至您选择或系统默认调用的第三方大模型服务提供商进行处理。</p><p>（2）<strong><strong>第三方大模型的后续使用</strong></strong>：第三方大模型服务提供商对您的输入内容的后续处理（包括是否存储、是否用于模型训练或优化、保留期限等），由其自身的隐私政策和服务协议约定。</p><p>（3）<strong><strong>本公司对用户内容的使用</strong></strong>：本公司可能将脱敏处理后的用户内容用于改进本平台的算法性能、服务质量分析等目的。</p><h3><strong>五、我们如何共享、转让和公开披露您的个人信息</strong></h3><p>1.<strong><strong>共享</strong></strong></p><p>（1）<strong><strong>向第三方大模型服务提供商共享</strong></strong>：为向您提供本服务，我们需要将您的输入内容传输至您选择调用的第三方大模型服务提供商。该等共享是提供本服务的必要组成部分。</p><p>（2）<strong><strong>向关联公司共享</strong></strong>：我们可能向关联公司共享部分个人信息，但仅限于本政策所述目的。</p><p>（3）<strong><strong>向服务提供商共享</strong></strong>：我们可能委托第三方服务提供商提供云存储、数据分析、客服系统等技术支持服务。我们会要求其按照我们的指示和法律法规要求处理个人信息。</p><p>（4）<strong><strong>依法定要求共享</strong></strong>：根据法律法规、监管要求、司法机关或行政机关的指令，我们可能需要披露您的个人信息。</p><p>2.<strong><strong>转让</strong></strong>。我们不会将您的个人信息转让给任何第三方，但以下情形除外：（1）在取得您明确同意的情况下；（2）在公司发生合并、分立、收购、资产转让等情形时。</p><p>3.<strong><strong>公开披露</strong></strong>。我们不会公开披露您的个人信息，但取得您明确同意或法律法规要求公开披露的情形除外。</p><h3><strong>六、个人信息的跨境传输</strong></h3><p>1.用户知悉并确认，根据您所在的地理位置以及您所访问或使用的本服务功能，您的个人数据可能会被传输至您居住国以外的地区，鉴于传输行为系由您主动选择触发，且本公司仅提供技术通道服务，针对跨境传输的合规路径，本公司将根据最终业务模式进行评估，但这不影响您作为数据出境的实际受益方应自行承担的合规注意义务。</p><h3><strong>七、我们如何存储和保护您的个人信息</strong></h3><p>1.<strong><strong>存储地点</strong></strong>。我们在中国境内收集和产生的个人信息，原则上将存储在中国境内。但在本政策第六条所述的跨境传输情形下，您的输入内容将根据第三方大模型服务提供商的数据存储政策存储在第三方的服务器上。</p><p>2.<strong><strong>存储期限</strong></strong>。我们仅在为提供本服务所必要的最短时间内保留您的个人信息，超出必要期限后，我们将对您的个人信息进行删除或匿名化处理。鉴于内测阶段，存储期限可能根据测试需要进行调整，具体以实际执行为准。</p><p>3.<strong><strong>安全保护措施</strong></strong>。我们已采取符合行业标准的技术安全措施和管理措施，保护您的个人信息安全，包括数据加密传输、访问权限控制等。<strong><strong>但鉴于内测阶段系统的不稳定性，您应自行承担部分数据安全风险。</strong></strong></p><p>4.<strong><strong>安全事件处置</strong></strong>。如发生个人信息安全事件，我们将按照法律法规的要求，及时向您和相关监管机构报告事件情况，并采取合理措施降低影响。</p><h3><strong>八、您的个人信息权利</strong></h3><p>1.根据《中华人民共和国个人信息保护法》，您对您的个人信息享有查阅、复制、更正、补充、删除、转移、限制处理、撤回同意、注销账户等权利。</p><p>2.<strong><strong>行使权利的方式</strong></strong>。如您需要行使上述权利，您可以通过本平台提供的功能设置自助操作，或通过本政策第十二条所列的联系方式与我们联系。我们将在收到您的请求后【15】个工作日内予以响应。</p><p>3.<strong><strong>内测期间的特殊说明</strong></strong>。在内测期间，由于系统功能尚不完善，部分自助权利行使功能可能暂时无法使用。您可以通过联系我们行使权利。</p><p><strong>九、用户查阅第三方政策的义务</strong></p><p>1.用户知悉并确认，不同大模型服务提供商对用户数据的收集、存储、使用、跨境传输规则、是否用于模型训练等事项均有其独立的规定。<strong><strong>您在使用特定大模型前，有义务自行登录该大模型服务提供商的官方网站，仔细查阅并了解其适用的《隐私政策》、《服务条款》或相关的数据保护声明。</strong></strong></p><h3><strong>十、关于未成年人信息的保护</strong></h3><p>1.本服务主要面向具备完全民事行为能力的成年人，且仅限于B端工业场景使用。我们不会在明知的情况下收集未满十四周岁的未成年人的个人信息。如您为未成年人，请勿使用本服务。</p><h3><strong>十一、本政策的更新与通知</strong></h3><p>1.我们可能根据测试需要、法律法规变化或业务发展，不时修订本政策。</p><p>2.修订后的政策将在本平台公布后生效。如您在修订后的政策生效后继续使用本服务，即视为您已接受修订后的政策。如您不同意修订后的政策，请您立即停止使用本服务并注销账户。</p><h3><strong>十二、联系我们</strong></h3><p>1.如您对本政策有任何疑问、意见或建议，或需要行使您的个人信息权利，请通过<strong><strong>电子邮箱</strong></strong>：docs@example.internal联系我们。</p><p>2.我们将在收到您的请求后【15】个工作日内予以回复，如您对我们的回复不满意，或认为我们对您个人信息的处理侵犯了您的合法权益，您可以向【本公司住所地】有管辖权的人民法院提起诉讼，或向相关监管部门投诉举报。</p>
"""
