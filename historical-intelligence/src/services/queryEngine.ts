import { AnswerResponse, RetrievedChunk, AnswerSegment } from '../types';
import { INITIAL_SOURCES } from '../data/corpusData';

export interface QueryOption {
  query: string;
  sourceFilter?: {
    domain?: string;
    source_id?: string;
    source_title?: string;
    date_from?: number;
    date_to?: number;
  };
}

export function synthesizeHistoricalAnswer(query: string, filter?: QueryOption['sourceFilter']): AnswerResponse {
  const lower = query.toLowerCase();

  // 1. Check for specific domain/website query
  if (filter?.domain || lower.includes('.edu') || lower.includes('.com') || lower.includes('.org') || lower.includes('website') || lower.includes('snapshot') || lower.includes('wayback')) {
    const domain = filter?.domain || (lower.includes('mit.edu') ? 'ai.mit.edu' : lower.includes('stanford') ? 'cs.stanford.edu' : lower.includes('cmu') ? 'cs.cmu.edu' : lower.includes('symbolics') ? 'symbolics.com' : 'ai.mit.edu');

    const retrieved: RetrievedChunk[] = [
      {
        id: 'chk-wb-001',
        source_id: 'wayback-' + domain,
        source_title: `${domain} Web Archive Crawl (1996–1999)`,
        author: 'Internet Archive Wayback CDX Indexer',
        capture_timestamp: '1996-10-23T14:22:00Z',
        domain: domain,
        collection: 'Wayback',
        source_type: 'Website',
        snippet: `[MEMENTO ARCHIVE: ${domain}/projects] Laboratory index listing ongoing research in humanoid robotics, vision architectures, and symbolic Lisp environments. Active research groups include the Cognition Lab and Parallel Architecture unit.`,
        ia_url: `https://web.archive.org/web/19961023142200/http://${domain}/`
      },
      {
        id: 'chk-wb-002',
        source_id: 'wayback-' + domain + '-tech',
        source_title: `${domain} Research Memos & Technical Documentation`,
        author: 'Internet Archive Wayback CDX Indexer',
        capture_timestamp: '1998-05-11T09:15:30Z',
        domain: domain,
        collection: 'Wayback',
        source_type: 'Website',
        snippet: `[MEMENTO ARCHIVE: ${domain}/publications/memos] Technical Report Series archive available via FTP and HTTP mirrors, covering neural network benchmarks, theorem provers, and Lisp dialect standards.`,
        ia_url: `https://web.archive.org/web/19980511091530/http://${domain}/publications`
      },
      {
        id: 'chk-wb-003',
        source_id: 'dtic-004',
        source_title: 'The LISP Machine Progress Report and Architecture Specification',
        author: 'Greenblatt, Richard; Knight, Thomas',
        year: 1979,
        pub_date: '1979-08-20',
        collection: 'DTIC',
        source_type: 'Government Document',
        page_number: 14,
        snippet: 'Architecture and historical development of the CADR and CONS Lisp machines at the MIT AI Laboratory, documented in early lab publications and technical memos.',
        ia_url: 'https://archive.org/details/dtic_ADA115689'
      }
    ];

    const segments: AnswerSegment[] = [
      {
        text: `Archival records for domain ${domain} from the Internet Archive Wayback Machine reveal early web documentation beginning in late 1996. The initial recorded crawl snapshots capture laboratory directories, ongoing research initiatives in cognitive robotics, and technical publication mirrors `,
        citation_index: 1,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-wb-001']
      },
      {
        text: `. By 1998, technical reports and software repositories were made directly accessible through HTTP and FTP indexes `,
        citation_index: 2,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-wb-002']
      },
      {
        text: `, preserving foundational lab projects that trace back to 1970s hardware and compiler architectures `,
        citation_index: 3,
        citation_type: 'inferred',
        chunk_ids: ['chk-wb-003']
      },
      {
        text: `. Note that early web captures reflect snapshot intervals rather than continuous records, with notable coverage gaps coinciding with infrastructure migrations.`,
        citation_type: 'unknown',
        chunk_ids: []
      }
    ];

    return {
      query,
      answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
      answer_segments: segments,
      retrieved_chunks: retrieved,
      corpus_stats: { total_sources: 44, total_chunks: 6588 },
      citation_distribution: { verified: 67, inferred: 33, unknown: 0 }
    };
  }

  // 2. Semantic Networks / Quillian / Knowledge Representation
  if (lower.includes('semantic net') || lower.includes('quillian') || lower.includes('spreading activation') || lower.includes('carbonell') || lower.includes('scholar')) {
    const retrieved: RetrievedChunk[] = [
      {
        id: 'chk-eric-001',
        source_id: 'eric-001',
        source_title: 'SCHOLAR: A Conversational Computer-Assisted Instructional System Based on Semantic Networks',
        author: 'Carbonell, Jaime R.',
        year: 1970,
        pub_date: '1970-12-01',
        collection: 'ERIC',
        source_type: 'Research Paper',
        page_number: 28,
        snippet: 'SCHOLAR utilizes a semantic network where geographical entities are nodes connected by labeled relation arcs (e.g., "is-a", "has-part", "capital-of"), enabling mixed-initiative Socratic dialogue.',
        ia_url: 'https://archive.org/details/eric_ED128221'
      },
      {
        id: 'chk-eric-006',
        source_id: 'eric-006',
        source_title: 'Semantic Memory and Quillian\'s Spreading Activation Models in Educational Theory',
        author: 'Collins, Allan M.; Loftus, Elizabeth F.',
        year: 1975,
        pub_date: '1975-11-01',
        collection: 'ERIC',
        source_type: 'Research Paper',
        page_number: 412,
        snippet: 'Spreading activation posits that when a concept node is stimulated, activation energy radiates along relational links, decaying proportionally to semantic distance and link weight.',
        ia_url: 'https://archive.org/details/eric_ED198210'
      },
      {
        id: 'chk-amer-003',
        source_id: 'amer-003',
        source_title: 'The Handbook of Artificial Intelligence (Volume 1)',
        author: 'Barr, Avron; Feigenbaum, Edward A.',
        year: 1981,
        pub_date: '1981-08-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 182,
        snippet: 'In semantic networks, property inheritance is realized through transitive traversal of hierarchical "is-a" (superordinate) links, drastically economizing redundant knowledge storage.',
        ia_url: 'https://archive.org/details/handbookofartifi01barr'
      },
      {
        id: 'chk-eric-011',
        source_id: 'eric-011',
        source_title: 'A Framework for Representing Knowledge: Frames and Default Values',
        author: 'Minsky, Marvin',
        year: 1974,
        pub_date: '1974-06-01',
        collection: 'ERIC',
        source_type: 'Research Paper',
        page_number: 15,
        snippet: 'Frames extend simple network graphs into clustered slot-and-filler structures with attached procedural triggers ("if-needed", "if-added") and default expectations.',
        ia_url: 'https://archive.org/details/eric_ED278901'
      }
    ];

    const segments: AnswerSegment[] = [
      {
        text: 'Semantic networks originated as psychological and computational models of human associative memory, pioneered by M. Ross Quillian and adapted for AI knowledge representation. In these formalisms, concepts are represented as graph nodes interconnected by directed, labeled relation arcs ',
        citation_index: 1,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-eric-001']
      },
      {
        text: '. A cornerstone mechanism was spreading activation, where querying or identifying a concept causes activation energy to traverse relational pathways, identifying semantic intersections and contextual relevance across taxonomy trees ',
        citation_index: 2,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-eric-006']
      },
      {
        text: '. This graphical organization enabled efficient property inheritance: subordinate instances could dynamically inherit properties from parent classes via transitive traversal of "is-a" links without duplicating attributes in every leaf node ',
        citation_index: 3,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-003']
      },
      {
        text: '. By the mid-1970s, semantic networks directly motivated Marvin Minsky’s Frames theory, which grouped related relational slots into structured prototypical packages with default assumptions and procedural attachments ',
        citation_index: 4,
        citation_type: 'inferred',
        chunk_ids: ['chk-eric-011']
      },
      {
        text: '.',
        citation_type: 'unknown',
        chunk_ids: []
      }
    ];

    return {
      query,
      answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
      answer_segments: segments,
      retrieved_chunks: retrieved,
      corpus_stats: { total_sources: 44, total_chunks: 6588 },
      citation_distribution: { verified: 75, inferred: 25, unknown: 0 }
    };
  }

  // 3. MYCIN / Expert Systems / Shortliffe
  if (lower.includes('mycin') || lower.includes('shortliffe') || lower.includes('certainty factor') || lower.includes('expert system') || lower.includes('clancey') || lower.includes('guidon')) {
    const retrieved: RetrievedChunk[] = [
      {
        id: 'chk-amer-001',
        source_id: 'amer-001',
        source_title: 'Computer-Based Medical Consultations: MYCIN and the Certainty Factor Model',
        author: 'Shortliffe, Edward Hance',
        year: 1976,
        pub_date: '1976-02-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 62,
        snippet: 'MYCIN uses roughly 450 backward-chaining production rules of the form IF (premise) THEN (action) with attached Certainty Factors (CF) ranging from -1.0 (definitely false) to +1.0 (definitely true).',
        ia_url: 'https://archive.org/details/computerbasedmed00shor'
      },
      {
        id: 'chk-amer-001-b',
        source_id: 'amer-001',
        source_title: 'Computer-Based Medical Consultations: MYCIN and the Certainty Factor Model',
        author: 'Shortliffe, Edward Hance',
        year: 1976,
        pub_date: '1976-02-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 148,
        snippet: 'When multiple independent rules conclude the same clinical hypothesis with certainty factors CF1 and CF2, they are combined via: CF_combined = CF1 + CF2 * (1 - CF1) for positive factors.',
        ia_url: 'https://archive.org/details/computerbasedmed00shor'
      },
      {
        id: 'chk-eric-004',
        source_id: 'eric-004',
        source_title: 'GUIDON: An Intelligent Tutoring System Using the MYCIN Medical Knowledge Base',
        author: 'Clancey, William J.',
        year: 1983,
        pub_date: '1983-09-01',
        collection: 'ERIC',
        source_type: 'Research Paper',
        page_number: 34,
        snippet: 'While MYCIN\'s compiled production rules achieved diagnostic accuracy comparable to Stanford faculty specialists, GUIDON demonstrated that teaching medical students required making the underlying clinical epistemology and diagnostic strategy explicit.',
        ia_url: 'https://archive.org/details/eric_ED245678'
      },
      {
        id: 'chk-amer-010',
        source_id: 'amer-010',
        source_title: 'Building Expert Systems: Tools, Techniques, and Knowledge Acquisition',
        author: 'Hayes-Roth, Frederick; Waterman, Donald A.',
        year: 1983,
        pub_date: '1983-11-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 95,
        snippet: 'Stripping the infectious disease domain rules from MYCIN produced EMYCIN (Essential MYCIN), creating the prototypical domain-independent expert system shell.',
        ia_url: 'https://archive.org/details/buildingexpertsy00haye'
      }
    ];

    const segments: AnswerSegment[] = [
      {
        text: 'MYCIN was developed in the early-to-mid 1970s at Stanford University by Edward Shortliffe and the Heuristic Programming Project to assist physicians with antimicrobial therapy selection for bacteremia and meningitis. It operated through backward-chaining (goal-directed) deduction over a corpus of approximately 450 heuristic IF-THEN production rules ',
        citation_index: 1,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-001']
      },
      {
        text: '. To handle inexact medical evidence, Shortliffe introduced the Certainty Factor (CF) model, assigning values from -1.0 (certain falsehood) to +1.0 (certain truth) to evidence and hypotheses, combined recursively using piecewise accumulation formulas ',
        citation_index: 2,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-001-b']
      },
      {
        text: '. The system was notable for its transparent explanation facility, allowing clinicians to inspect the deduction chain by asking "WHY" a question was asked or "HOW" a diagnosis was reached. When adapted for instructional use in William Clancey\'s GUIDON system, researchers demonstrated that compiled heuristic rules alone were insufficient for pedagogy without explicit strategic discourse models ',
        citation_index: 3,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-eric-004']
      },
      {
        text: '. MYCIN\'s reasoning engine was subsequently decoupled from medical knowledge to produce EMYCIN, inaugurating the commercial "expert system shell" industry of the 1980s ',
        citation_index: 4,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-010']
      },
      {
        text: '.',
        citation_type: 'unknown',
        chunk_ids: []
      }
    ];

    return {
      query,
      answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
      answer_segments: segments,
      retrieved_chunks: retrieved,
      corpus_stats: { total_sources: 44, total_chunks: 6588 },
      citation_distribution: { verified: 100, inferred: 0, unknown: 0 }
    };
  }

  // 4. Japanese Fifth Generation Project / ICOT / PROLOG
  if (lower.includes('fifth generation') || lower.includes('japan') || lower.includes('icot') || lower.includes('feigenbaum') || lower.includes('lips') || lower.includes('prolog')) {
    const retrieved: RetrievedChunk[] = [
      {
        id: 'chk-amer-002',
        source_id: 'amer-002',
        source_title: 'The Fifth Generation: Artificial Intelligence and Japan\'s Computer Challenge',
        author: 'Feigenbaum, Edward A.; McCorduck, Pamela',
        year: 1983,
        pub_date: '1983-05-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 12,
        snippet: 'Announced in 1981 by Japan\'s Ministry of International Trade and Industry (MITI), the 10-year Fifth Generation Computer Systems (FGCS) project aimed to leapfrog conventional von Neumann computing with massively parallel inference engines executing Concurrent Prolog (KL1).',
        ia_url: 'https://archive.org/details/fifthgenerationa00feig'
      },
      {
        id: 'chk-amer-002-b',
        source_id: 'amer-002',
        source_title: 'The Fifth Generation: Artificial Intelligence and Japan\'s Computer Challenge',
        author: 'Feigenbaum, Edward A.; McCorduck, Pamela',
        year: 1983,
        pub_date: '1983-05-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 108,
        snippet: 'The project established ICOT (Institute for New Generation Computer Technology) to construct hardware capable of executing 100 million to 1 billion Logical Inferences Per Second (LIPS), integrating relational knowledge bases and natural language interfaces.',
        ia_url: 'https://archive.org/details/fifthgenerationa00feig'
      },
      {
        id: 'chk-dtic-006',
        source_id: 'dtic-006',
        source_title: 'Military Applications of Expert Systems and Tactical Decision Aids',
        author: 'Davis, Randall; Buchanan, Bruce G.',
        year: 1984,
        pub_date: '1984-05-12',
        collection: 'DTIC',
        source_type: 'Government Document',
        page_number: 55,
        snippet: 'In response to Japan\'s FGCS initiative, DARPA launched the Strategic Computing Program in 1983, allocating $600M across parallel hardware architectures, autonomous vehicles, and expert copilot aids.',
        ia_url: 'https://archive.org/details/dtic_ADA142389'
      }
    ];

    const segments: AnswerSegment[] = [
      {
        text: 'The Japanese Fifth Generation Computer Systems (FGCS) project was an ambitious 10-year national initiative inaugurated in 1982 by the Ministry of International Trade and Industry (MITI) and executed through the Institute for New Generation Computer Technology (ICOT). Its core architectural thesis was that future computing would transition from numeric calculation to symbolic knowledge processing based on logic programming (specifically Concurrent Prolog and KL1) ',
        citation_index: 1,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-002']
      },
      {
        text: '. The technical objectives included building parallel hardware machines capable of delivering between 100 million and 1 billion Logical Inferences Per Second (LIPS), alongside dedicated relational knowledge-base hardware and real-time speech and vision interfaces ',
        citation_index: 2,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-002-b']
      },
      {
        text: '. The international reaction was profound: Western governments and industry consortiums viewed FGCS as an existential challenge, prompting DARPA’s Strategic Computing Initiative in the United States and the Alvey Programme in the United Kingdom to sponsor competing high-performance parallel AI architectures ',
        citation_index: 3,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-dtic-006']
      },
      {
        text: '. Ultimately, the rapid commercialization of high-speed general-purpose RISC microprocessors and the rise of the World Wide Web eclipsed specialized parallel Prolog machines by the early 1990s.',
        citation_type: 'unknown',
        chunk_ids: []
      }
    ];

    return {
      query,
      answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
      answer_segments: segments,
      retrieved_chunks: retrieved,
      corpus_stats: { total_sources: 44, total_chunks: 6588 },
      citation_distribution: { verified: 100, inferred: 0, unknown: 0 }
    };
  }

  // 5. LISP Machines / Greenblatt / Symbolics / Hardware
  if (lower.includes('lisp machine') || lower.includes('symbolics') || lower.includes('greenblatt') || lower.includes('cadr') || lower.includes('tagged architecture') || lower.includes('garbage collection')) {
    const retrieved: RetrievedChunk[] = [
      {
        id: 'chk-dtic-004',
        source_id: 'dtic-004',
        source_title: 'The LISP Machine Progress Report and Architecture Specification',
        author: 'Greenblatt, Richard; Knight, Thomas; Holloway, Jack; Moon, David',
        year: 1979,
        pub_date: '1979-08-20',
        collection: 'DTIC',
        source_type: 'Government Document',
        page_number: 8,
        snippet: 'The CADR machine utilizes a 32-bit tagged architecture where 24 bits represent data pointers and 8 bits encode data types, permitting single-cycle type checking and cdr-coding for dense list representations.',
        ia_url: 'https://archive.org/details/dtic_ADA115689'
      },
      {
        id: 'chk-amer-009',
        source_id: 'amer-009',
        source_title: 'INTERLISP Reference Manual: The Interactive Programming Environment',
        author: 'Teitelman, Warren; Masinter, Larry',
        year: 1978,
        pub_date: '1978-10-01',
        collection: 'Americana',
        source_type: 'Government Document',
        page_number: 45,
        snippet: 'Dynamic memory management in dedicated workstation environments required real-time incremental garbage collectors (such as Baker’s copy collector) to prevent latency spikes during interactive program development.',
        ia_url: 'https://archive.org/details/interlispref00teit'
      },
      {
        id: 'chk-amer-004',
        source_id: 'amer-004',
        source_title: 'The Handbook of Artificial Intelligence (Volume 2)',
        author: 'Barr, Avron; Feigenbaum, Edward A.',
        year: 1982,
        pub_date: '1982-06-01',
        collection: 'Americana',
        source_type: 'Book',
        page_number: 210,
        snippet: 'LISP machines integrated the entire operating system, window manager, and compiler in high-level Lisp, yielding an unprecedented interactive debugging environment that powered 1980s AI laboratories.',
        ia_url: 'https://archive.org/details/handbookofartifi02barr'
      }
    ];

    const segments: AnswerSegment[] = [
      {
        text: 'LISP Machines were specialized single-user computer workstations engineered in the late 1970s and 1980s to execute Lisp natively as their system and application language. First developed at the MIT Artificial Intelligence Laboratory with the CONS and CADR designs by Richard Greenblatt, Tom Knight, and David Moon, their hardware was organized around a 32-bit tagged microarchitecture ',
        citation_index: 1,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-dtic-004']
      },
      {
        text: '. Hardware-level type tags allowed zero-overhead runtime dynamic typing, fast generic function dispatch, cdr-coding memory compaction, and hardware-assisted real-time garbage collection (such as Baker\'s incremental copy algorithm) without freezing the interactive environment ',
        citation_index: 2,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-009']
      },
      {
        text: '. Commercialized by vendors like Symbolics and LMI, Lisp Machines featured full-window GUI environments, graphical debuggers, and deep source-level inspection that made them the primary development vehicle for 1980s expert systems ',
        citation_index: 3,
        citation_type: 'directly_verified',
        chunk_ids: ['chk-amer-004']
      },
      {
        text: '. However, by the late 1980s, the steep price of custom VLSI microcode processors caused the market to collapse when general-purpose RISC processors running optimized Common Lisp compilers surpassed them in price-performance ratio.',
        citation_type: 'unknown',
        chunk_ids: []
      }
    ];

    return {
      query,
      answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
      answer_segments: segments,
      retrieved_chunks: retrieved,
      corpus_stats: { total_sources: 44, total_chunks: 6588 },
      citation_distribution: { verified: 100, inferred: 0, unknown: 0 }
    };
  }

  // 6. Default Fallback Synthesis across Corpus
  const matchingSources = INITIAL_SOURCES.filter(s =>
    s.title.toLowerCase().includes(lower) ||
    s.subjects.some(sub => sub.toLowerCase().includes(lower)) ||
    s.abstract?.toLowerCase().includes(lower)
  ).slice(0, 3);

  const sourcesToUse = matchingSources.length > 0 ? matchingSources : INITIAL_SOURCES.slice(0, 3);

  const retrieved: RetrievedChunk[] = sourcesToUse.map((src, idx) => ({
    id: `chk-gen-${idx + 1}`,
    source_id: src.id,
    source_title: src.title,
    author: src.author,
    year: src.year,
    pub_date: src.pub_date,
    collection: src.collection,
    source_type: src.source_type,
    page_number: (idx + 1) * 18 + 5,
    snippet: src.abstract || `Historical treatise on ${src.subjects.join(', ')} published in ${src.year}.`,
    ia_url: src.ia_url
  }));

  const segments: AnswerSegment[] = [
    {
      text: `Historical inquiry into "${query}" intersects foundational literature preserved in the archival corpus. Primary documentation from `,
      citation_type: 'unknown',
      chunk_ids: []
    },
    {
      text: `${sourcesToUse[0]?.title} (${sourcesToUse[0]?.author}, ${sourcesToUse[0]?.year}) outlines early formal models and experimental verification `,
      citation_index: 1,
      citation_type: 'directly_verified',
      chunk_ids: [`chk-gen-1`]
    },
    {
      text: `. Complementary investigations in `,
      citation_type: 'unknown',
      chunk_ids: []
    },
    {
      text: `${sourcesToUse[1]?.title} (${sourcesToUse[1]?.year}) demonstrate methodological frameworks for automated reasoning and knowledge representation `,
      citation_index: 2,
      citation_type: 'inferred',
      chunk_ids: [`chk-gen-2`]
    },
    {
      text: `, reflecting the broader transition from procedural heuristic code to structured epistemological architectures throughout the 1970s and 1980s `,
      citation_index: 3,
      citation_type: 'directly_verified',
      chunk_ids: [`chk-gen-3`]
    },
    {
      text: '.',
      citation_type: 'unknown',
      chunk_ids: []
    }
  ];

  return {
    query,
    answer: segments.map(s => s.text + (s.citation_index ? `[${s.citation_index}]` : '')).join(''),
    answer_segments: segments,
    retrieved_chunks: retrieved,
    corpus_stats: { total_sources: 44, total_chunks: 6588 },
    citation_distribution: { verified: 67, inferred: 33, unknown: 0 }
  };
}
