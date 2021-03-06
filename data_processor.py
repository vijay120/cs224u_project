import os
import xml.etree.ElementTree as ET
from chemlistem import get_mini_model, get_trad_model, get_ensemble_model



dataset = ['DrugBank', 'MedLine']


def get_er_model(model='ensemble-chemlistem'):
    if model == 'traditional-chemlistem':
        return get_trad_model()
    elif model == 'mini-chemlistem':
        return get_mini_model()
    elif model == 'ensemble-chemlistem':
        return get_ensemble_model()


def read_xml_file(file_path, verbose=False):
    if verbose:
        print(file_path)
    return ET.parse(file_path).getroot()


class Entity:
    def __init__(self, entity_id, char_offset=None, type=None, text=None):
        self._id = entity_id
        self.char_offset = char_offset
        self.type = type
        self.text = text

    @staticmethod
    def from_xml(xml_object):
        entity = Entity(
            xml_object.attrib['id'],
            char_offset=xml_object.attrib['charOffset'],
            type=xml_object.attrib['type'],
            text=xml_object.attrib['text']
        )
        return entity


class Sentence:
    def __init__(self, sent_id, text=None, entities=None):
        self._id = sent_id
        self.text = text or ''
        self.entities = entities or []
        # entity pair map
        self.map = {}

    @staticmethod
    def from_xml(xml_object):
        sent = Sentence(xml_object.attrib['id'], text=xml_object.attrib['text'])
        entity_count = 0
        for entity in xml_object.iter('entity'):
            sent.entities.append(Entity.from_xml(entity))
            entity_count += 1

        pair_count = 0
        for pair in xml_object.iter('pair'):
            if pair.attrib['ddi'] == 'true':
                e1 = pair.attrib['e1']
                e2 = pair.attrib['e2']
                mechanism = pair.attrib['type']
                sent.map[e1] = (e2, mechanism)
            pair_count += 1

        if pair_count != entity_count*(entity_count-1)/2:
            print('Potential data issue for sentence ', sent._id)

        return sent


class Document:
    def __init__(self, doc_id, sentences=None):
        self._id = doc_id
        self.sentences = sentences or []

    @staticmethod
    def read_from_xml(filepath, verbose=False):
        return Document.from_xml(read_xml_file(filepath, verbose=verbose))

    @staticmethod
    def from_xml(xml_object):
        doc = Document(xml_object.attrib['id'])
        for sentence in xml_object.iter('sentence'):
            doc.sentences.append(Sentence.from_xml(sentence))
        return doc


class Dataset:
    def __init__(self, name, documents=None):
        self.name = name
        self.documents = documents or []

    @staticmethod
    def from_training_data(name, verbose=False):
        ds = Dataset(name)
        path = "./Train/" + name
        for _, _, files in os.walk(path, topdown=False):
            if verbose:
                print(files)
            for filename in files:
                filepath = path + '/' + filename
                if '.xml' in filename:
                    ds.documents.append(Document.read_from_xml(filepath, verbose=verbose))
        return ds


def check_sentence(sent, p1=None, p2=None):
    keywords = ['adverse', 'concern', 'inadvertently', 'inadvertent', 'adversely']
    if p1 and p2:
        sent = sent[p1:p2]
    for keyword in keywords:
        if keyword in sent:
            return True
    return False


def findall(p, s):
    '''Yields all the positions of
    the pattern p in the string s.'''
    i = s.find(p)
    while i != -1:
        yield i
        i = s.find(p, i+1)


def transform_pubmed(num_files=None):
    source = './Raw/pubmed_Drug-Drug_interaction_abstract_result.xml'
    root = read_xml_file(source)
    count = 0

    er_model = get_er_model()

    for article in root.iter('PubmedArticle'):
        sentences = []

        for title in article.iter('ArticleTitle'):
            print('Title')
            title = "".join(title.itertext())
            sentences.append(title)
            print(title)

        for text in article.iter('AbstractText'):
            print('Abstract')
            abstract = "".join(text.itertext())
            for sentence in abstract.split('.'):
                sentences.append(sentence)
            print(abstract)

        article_id = None
        for id_list in article.iter('ArticleIdList'):
            for id_e in id_list.iter('ArticleId'):
                if id_e.attrib['IdType'] == 'pubmed':
                    print('ID')
                    article_id = "".join(id_e.itertext())
                    print(article_id)
                    break
            break

        root = ET.Element("document", attrib={'id': article_id})
        abbr_dic = {}

        # example of entity ID: DDI-DrugBank.d532.s2.e0
        sent_count = 1
        for sentence in sentences:
            sentence_element = ET.SubElement(root, 'sentence', attrib={'text': sentence})
            entities = er_model.process(sentence)
            entity_loc_map = {}

            # Adding any abbreviation to the abbreviation dictionary
            for (start, end, entity, _, _) in entities:
                if len(entity) <= 5:
                    print('abbreviation:', entity)
                    abbr_dic[entity] = 1
                elif end + 1 < len(sentence) and sentence[start - 1] == '(' and sentence[end + 1] == ')':
                    print('abbreviation:', entity)
                    abbr_dic[entity] = 1
                entity_loc_map[start] = (entity, end)

            # Getting any additional abbreviation
            for abbr in abbr_dic:
                for ent_start in findall(abbr, sentence):
                    if ent_start not in entity_loc_map:
                        print('Detecting an unrecognized abbreviation {} at {}'.format(abbr, ent_start))
                        ent_end = ent_start + len(entity) - 1
                        entity_loc_map[ent_start] = (entity, ent_end)
                        entities.append((ent_start, ent_end, abbr, None, None))

            entity_map = []
            entity_count = 0
            for (start, end, entity, _, _) in entities:
                entity_id = "DDI-PubMed.{}.s{}.e{}".format(article_id, sent_count, entity_count)
                ET.SubElement(sentence_element, 'entity', attrib={'text': entity, 'charOffset': str(start) + '-' + str(end), 'id': entity_id})
                entity_map.append((entities[entity_count], entity_id, start))
                entity_count += 1

            # sort entities in order of start
            entity_map.sort(key=lambda x: x[2])
            for i in range(len(entity_map) - 1):
                for j in range(i, len(entity_map)):
                    (entity1, id1, start1) = entity_map[i]
                    (entity2, id2, start2) = entity_map[j]
                    if check_sentence(sentence, start1, start2):
                        ET.SubElement(sentence_element, 'pair', attrib={'e1': id1, 'e2': id2, 'ddi': "true"})
                        print("Pair:", entity1, entity2)
                        print(sentence)
                    else:
                        ET.SubElement(sentence_element, 'pair', attrib={'e1': id1, 'e2': id2, 'ddi': "false"})
            sent_count += 1

        et = ET.ElementTree(root)
        et.write('./Train/PubMed/' + article_id + '.xml', encoding='utf-8', xml_declaration=True)
        count += 1
        print('--')
        if num_files and count >= num_files:
            break


#transform_pubmed(num_files=10)


