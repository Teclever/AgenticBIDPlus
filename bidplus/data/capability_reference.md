# Company Capability & Technology Reference Guide
**Purpose:** Evaluation matrix for determining whether a prospective project aligns with company capabilities. Used by an LLM to produce a structured 0–5 capability score.

---

## 1. Evaluation Instructions

When analyzing a new project description:

- **Direct Match (score 4–5):** Project domain and technology stack align with a Core Domain below and technologies appear in the Primary Technology Stack.
- **Adjacent Match (score 2–3):** Project requires a technology or domain not explicitly listed but functionally equivalent to what is proven (e.g., Google Cloud instead of AWS/Azure, Vue.js instead of React, a Siemens PLC instead of Beckhoff TwinCAT, Azure OpenAI instead of AWS Bedrock). Engineering foundation allows adaptation within established domains.
- **Out of Scope (score 0–1):** Project has no meaningful overlap with the engineering, aerospace, defense, enterprise SaaS, or heavy industrial focus. Examples: consumer mobile games, social media marketing, SAP/Oracle ERP implementation, chip/ASIC design, pure cybersecurity red-teaming, blockchain/Web3, general e-commerce retail.

---

## 2. Scoring Rubric

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Direct in-scope | Domain is a proven Core Domain AND majority of required tech appears in the Primary Technology Stack AND client type matches the proven portfolio (defense PSU, ISRO, US Federal, enterprise SaaS). |
| **4** | Strong match | Domain is proven but tech stack has 1–2 gaps that are learnable extensions, OR domain is adjacent with near-complete tech overlap. |
| **3** | Moderate — pursue with ramp-up | Domain is adjacent (e.g., automotive HIL vs. avionics ATE, energy SCADA vs. industrial automation), OR tech stack is ~50% proven, OR standards are unfamiliar but methodology is transferable. |
| **2** | Weak — assess further | Only one dimension aligns (tech OR domain but not both); significant new capability investment required. |
| **1** | Fringe | Superficial overlap only (e.g., uses a language we know but domain is entirely foreign). |
| **0** | Out of scope | No meaningful overlap in domain, technology, or standards. Decline. |

**Scoring note:** Weight domain alignment and technology stack match most heavily. A project scoring 5 on domain but 2 on tech stack should yield an overall ~3. Use intermediate scores freely — they are expected.

---

## 3. Core Domains

1. **Aviation Simulator Systems** — Real-time simulation interfaces, outside visual imagery systems, data acquisition/control for aircraft and engine simulation environments. Clients: HAL, ADA.

2. **Cloud and Data Services** — Cloud migration, infrastructure automation, multi-cloud scalability, serverless optimization. Clients: startups, EdTech, media, logistics firms.

3. **Custom Electronics & Product Engineering** — Turnkey hardware/software product engineering, embedded systems, RTOS porting, BSP/driver development, edge computing device design. Clients: BEL, ADA, ADE, ISRO IPRC, automotive OEMs.

4. **Data & Telemetry** — Real-time data acquisition, telemetry system design, ground station integration, environmental monitoring for aerospace/defense/space. Clients: ADA, SDSC SHAR, ADE, NTT DoCoMo.

5. **Data Acquisition Systems (DAS)** — High-channel-count DAS (up to 6,000+ channels) for propulsion, engine, and battery test facilities; real-time FFT, trending, and automated reporting. Clients: ISRO IPRC, Battery OEMs.

6. **Industrial Automation** — PC-based and RTOS-driven control systems for industrial automation, scientific instruments, propulsion test facilities, and additive manufacturing machines. Clients: CMTI, IIAP, ISRO LPSC, Indian Defence.

7. **IT Services & Enterprise SaaS** — Enterprise platform development, compliance SaaS, and CRM implementations. Proven in fintech, mortgage, and US Federal Government compliance contexts. Clients: SavvyMoney, VIP Mortgage, US Federal Govt via MGT Consulting.

8. **Next-Generation Tech** — LLM/RAG pipelines, Agentic AI, AI analytics automation, autonomous ground vehicles (ROS). Clients: US Federal Govt via MGT Consulting, ADA, CVRDE.

9. **Onboard Avionics** — Embedded software to DO-178C Level A/B standards, CSU-level testing, dual-redundant subsystem design for flight-critical LRUs. Clients: ADA, HAL.

10. **Specialized Engineering Services** — Avionics simulator integration, software IV&V, legacy Fortran/Ada migration, LRU software upgradation. Clients: BEL, ADA, ADA via Safran.

11. **Test Rigs & Checkout Systems** — Automated test equipment (ATE) and checkout systems for avionics LRUs, flight control computers, and mission computers. Largest domain: 13 delivered projects. Clients: HAL, BEL, ADA, ADE.

---

## 4. Primary Technology Stack

### Languages & Frameworks
- **Languages:** C, C++, Embedded C, Python, Java, Ada 95, Fortran, C#, HTML, ReactJS
- **Frameworks:** QT, PyQT, JavaFX, Spring Boot, Django, Apache Tomcat, LabVIEW, MATLAB/Simulink

### AI, Cloud & Enterprise
- **AI / ML:** AWS Bedrock, LLMs, RAG, Vector DB, Agentic AI, Machine Learning (Python/ETL), Pandas, Einstein AI (Salesforce), YoLo (edge/FPGA)
- **Cloud:** AWS (EC2, S3, RDS, Lambda, EKS, Step Functions, Bedrock), Azure (VMs, AKS, Migrate, Site Recovery), GCP (GKE)
- **DevOps:** Terraform, Ansible, Docker, Kubernetes
- **Enterprise CRM:** Salesforce (Community, Sales, Marketing Cloud, Lightning, Visualforce, Einstein AI)
- **Databases:** Oracle 12c, PostgreSQL, MySQL, MongoDB

### Embedded, RTOS & Hardware
- **RTOS / OS:** Xenomai RTOS, RT Linux, WindRiver RT Linux, Hard RTOS, Linux (embedded), TwinCAT 3 (Beckhoff), ROS-Humble, Android OS (customized)
- **Processors / SoC / FPGA:** TI Sitara AM5718, ADI Blackfin 609, Xilinx Zynq-7000, MPC5777C (PowerPC), MC68332, STM32, PXI, UEI hardware
- **Protocols:** MIL-STD-1553B, ARINC 429, EtherCAT, RTnet, OPC/OPC UA, RS-232/422/485, SPI, I2C, UART, PCIe, MQTT, RTSP, Ethernet/UDP, Synchro, TSN Ethernet
- **Automation Hardware:** Beckhoff (TwinCAT 3, EtherCAT terminals, TwinSAFE), PXI rack/instrumentation, UEI DAQ modules
- **Tools:** LDRA TBvision/TBrun, Keil uVision, SPIL, SCADA, Wonderware HMI, AdaMULTI IDE, PCM Decommutation, IMAT21 DPMAS V1.0

### Standards & Certifications
- **Avionics:** DO-178C (Level A, B, D), MISRA C, CEMILAC qualification
- **Defense / Test:** MIL-STD-1553B, IMTAR (Indian MoD ATE standard), ARINC 429
- **Enterprise / Federal:** 2 CFR Part 200 (US Federal cost allocation)

---

## 5. Domain-Specific Keywords

*Terms that appear in project descriptions and map to a Core Domain. Presence of these signals strong domain alignment even if not mentioned in the tech stack.*

**Aviation Simulator Systems**
Full Flight Simulator, FFS, Level-D simulator, cockpit interface, cockpit signal management, simulation host computer, outside visual system, OWS, terrain rendering, visual imagery system, DACS, METF, mobile engine test

**Cloud and Data Services**
Cloud migration, lift-and-shift, IaC, infrastructure as code, disposable lab environment, serverless architecture, cloud-native re-architecture, multi-cloud deployment, VMWare migration, on-premises to cloud, auto-scaling, CDN, object storage

**Custom Electronics & Product Engineering**
BSP, board support package, device driver development, RTOS porting, kernel module, bare-metal, hard real-time, PXI porting, dual-server redundancy, cryogenic control, HDVSD, airborne video recorder, sonar product, edge AI, YoLo FPGA, Zynq SoC, multimedia middleware

**Data & Telemetry**
Flight test instrumentation, FTI, PCM decommutation, ground telemetry station, telemetry ground station, GCS, ground control station, UAV data collection, met tower, meteorological monitoring, launch range monitoring, emergency warning system, EWS, cell broadcast, EMPLTS, EOT, ELCF, engine parts life tracking

**Data Acquisition Systems**
DAQ, DAS, data acquisition system, propulsion test facility, engine test stand, test bench DAQ, EtherCAT DAQ, UEI modules, high channel count, 1553-channel, analog input channel, FFT on test data, real-time trending, battery test bench, BMS test, battery management validation, semi-cryo engine test, liquid propulsion test

**Industrial Automation**
Beckhoff, TwinCAT, EtherCAT motion control, telescope control system, TCS, observatory control, directed energy deposition, DED machine, additive manufacturing control, SLM control, hard real-time process control, Wonderware HMI, OPC UA, SCADA control, liquid propulsion valve control, cryogenic valve

**IT Services & Enterprise SaaS**
Salesforce implementation, Salesforce Apex, Lightning Web Components, CRM customization, fintech SaaS, compliance platform, 2 CFR Part 200, OMB A-87, federal cost allocation, multi-tenant SaaS, mortgage software, loan origination, credit score platform, billing automation

**Next-Generation Tech**
RAG pipeline, retrieval augmented generation, agentic AI, AI agent, LLM pipeline, knowledge assistant, document QA, autonomous ground vehicle, UGV, UGCV, ROS2, navigation stack, SLAM, path planning, aircraft health monitoring, AHM, predictive maintenance ML, ETL ML pipeline, AI report generation, Map-Reduce LLM, variance analysis automation

**Onboard Avionics**
DO-178C Level A, DO-178C Level B, avionics LRU software, CSU-level testing, Computer Software Unit, MISRA C compliance, LDRA analysis, Ada 95, GNAT, dual-redundant avionics, flight-critical software, BCCIU, BHEEM, engine vibration tracking, environmental control system software, fuel management software, LCA Mk2, AMCA, CEMILAC, RCMA

**Specialized Engineering Services**
IV&V, independent verification and validation, IMTAR compliance, ATE IV&V, Fortran cross-compilation, Fortran porting, legacy avionics migration, VOB migration, ClearCase, avionics bird simulator, pilot-in-the-loop, LRU validation simulator, software qualification, LDRA certification support

**Test Rigs & Checkout Systems**
ATE, automated test equipment, LRU tester, SRU tester, checkout system, DFCC tester, FCMC tester, WMC ATE, weapons management computer tester, mission computer ATE, DUCTE, DARIN3, IFCC tester, PXI ATE, MIL-1553 bus simulation, ARINC bus simulation, RS-422 signal simulation, Synchro signal, GO/NOGO, PBIT, PLBIT, squadron tester, field maintenance tester, avionics integration rig, AIR, SPIL, LabVIEW ATE, MATLAB Simulink HIL, HIL test

---

## 6. Required Output Format

Always respond with the following structure. Do not deviate.

```
SCORE: [0–5]
CONFIDENCE: [High / Medium / Low]
DOMAIN MATCH: [Primary Core Domain name(s)]
MATCHING TECH: [Comma-separated list of matched technologies/standards from Section 4]
GAPS: [Technologies or domain knowledge required but absent from portfolio. Write "None" if score is 5.]
RATIONALE: [2–3 sentences citing specific evidence from this document.]
RECOMMENDATION: [PURSUE | PURSUE WITH RAMP-UP | ASSESS FURTHER | DECLINE]
```

**Recommendation mapping:** PURSUE = score 4–5 | PURSUE WITH RAMP-UP = score 3 | ASSESS FURTHER = score 2 | DECLINE = score 0–1

---

## 7. Worked Example

**Input project description:**
> "Development of a LabVIEW-based automated test system for a radar LRU for DRDO NPOL, requiring MIL-STD-1553B bus simulation and RS-422 signal interfaces."

**Expected output:**
```
SCORE: 4
CONFIDENCE: High
DOMAIN MATCH: Test Rigs & Checkout Systems
MATCHING TECH: LabVIEW, MIL-STD-1553B, RS-422
GAPS: Radar / EW LRU domain is new — portfolio covers avionics LRUs (DFCC, WMC, mission computers), not radar or electronic warfare hardware. DRDO NPOL is a new lab within the known DRDO client group.
RATIONALE: LabVIEW-based ATE with MIL-1553B and RS-422 is a direct technical match across multiple delivered projects (DUCTE mission computer ATE, IFCC channel testers, DFCC squadron tester). DRDO is a proven client type (CVRDE engagement exists). The radar LRU domain requires modest domain ramp-up but the test architecture is identical to proven work.
RECOMMENDATION: PURSUE
```
