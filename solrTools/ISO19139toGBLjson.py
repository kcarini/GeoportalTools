# BEN HICKSON
# DEC 21, 2017

# SCRIPT TAKES A GIVEN DIRECTORY CONTAINING XML FILES FOLLOWING THE ISO 19139 FORMAT AND CONVERTS THEM TO JSON FILES
#  FORMATTED TO THE GEOBLACKLIGHT SCHEMA. BASED ON A fvn-1a HASH OF THE DATASET TITLE THE OUTPUT JSON FILES ARE WRITTEN
#  TO A NEW DIRECTORY BASED ON THE HASH. SEE THE setOutDir FUNCTION FOR MORE INFO.

# VARIABLES OF NOTE
#   IF THE tosolr ARGUMENT IS PASSED THE JSON STRING WILL BE POSTED IN AN UPDATE REQUEST TO THE SOLR COLLECTION URL
#  SPECIFIED IN THE solr_loc variable
#   THE LIST OF COLLECTIONS (collections) WHICH THE RECORD BELONGS TO IS DERIVED FROM THE EXISTING DIRECTORY STRUCTURE
#  WHERE THE XML FILE IS HELD. E.G. IF THE XML FILE IS IN "./imagery/aerial photographs/USDA/NAIP/" THE COLLECTION LIST
#  IN THE JSON WILL BE [imagery, aerial photographs, USDA, NAIP]

import json, os, ogr, re, shutil, requests, argparse, struct, base64
from lxml import etree as ET
from collections import OrderedDict
from xml.dom import minidom as md
from fnv64basedhash import hash_dn

print("Starting translation of xml files in folder")
# Apache Solr Collection URL. E.g. http://localhost:8080/solr/collection1
solr_loc = "http://geotest.library.arizona.edu:8983/solr/UAL_GeospatialRecords"
solrURL = solr_loc + "/update?commit=true"
# GeoServer Location
geoserver_loc = "https://geo.library.arizona.edu/geoserver"


parser = argparse.ArgumentParser(description="Takes a given directory containing xml files following the ISO 19139"
                                             " format and converts them to JSON files following the GeoBlacklight"
                                             " schema.")
parser.add_argument("-o", "--outdir", type=str, help="Output parent directory where processed files and folders will be"
                                                     " created. Defaults to the current directory.")
parser.add_argument("-m", "--mddir", type=str, help="Location of the XML metadata files. Defaults"
                                                    " to the current directory.")
parser.add_argument("-d", "--datadir", type=str, help="Directory location where geospatial datasets reside. If not"
                                                      " specified, the script directory is used.")
parser.add_argument("-r", "--rights", type=str, help="Access rights - should be \"Public\" or \"Restricted\". Default"
                                                     " is Public.")
parser.add_argument("-i", "--institution", type=str, help="Institution holding the dataset. Default is UArizona")
parser.add_argument("-v", "--version", type=str, help="Geoblacklight Schema Version. Default is 1.0")
parser.add_argument("-w", "--workspace", type=str, help="Geoserver workspace where the dataset is held. Used for OGC"
                                                        " services (wms, wcs, wfs). Default is UniversityLibrary")
parser.add_argument("-u", "--mdurl", type=str, help="Prefix for the URL where the full xml metadata record can be"
                                                    " found. Default is \"https://raw.githubusercontent.com/OpenGeoMetadata/edu.\" + institution.lower()")
parser.add_argument("-t", "--tosolr", type=str, help="True/False value indicating if the composed gbl schema should be"
                                                     " posted to the url identified by the solr_loc variable. Default is"
                                                     " False.")



def checkpath(path):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        print("ERROR: Dataset or directory \"" + path + "\"cannot be found.")
        exit()
    else:
        return path


def findFile(xmlFile):
    dataName = xmlFile[:-4]  # Remove xml extension, should still have data extension (.tif or .shp)
    try:
        fpath = filelist[dataName]
        return fpath
    except:
        print("ERROR: Unable to find the geospatial dataset %s in the data directory %s. Exiting." % (dataName, datadir))
        exit()


def getDataType(file):
    datafile = findFile(file)
    if datafile:
        ext = file.split(".")[1]
        if ext == "tif":
            return ["Raster", "Image"]
        elif ext == "shp":
            driver = ogr.GetDriverByName("ESRI Shapefile")
            file = driver.Open(datafile, 0)
            layer = file.GetLayer()
            sampleFeature = layer[0]
            geom = sampleFeature.GetGeometryRef().ExportToWkt().split(" ")[0]
            geomFormat = geom[0] + geom[1:].lower()
            if geomFormat == "Linestring":
                geomFormat = "Line"
            if geomFormat == "Multipolygon":
                geomFormat = "Polygon"
            return [geomFormat, "Dataset"]
    else:
        print("Can't Find File")


def getSlugWords(file):
    wordlist = re.split("\W+|_", file)
    wordstring = ""
    for word in wordlist:
        wordstring += "-" + word.lower()
    return (wordstring)


def getSingleValue(path):
    path_string = ""
    for i in range(0, len(path) - 1):
        path_string += path[i]
        if i != len(path) - 1:
            path_string += "/"
    element = root.find(path_string, namespaces)
    text = element.text

    return (text)


def getMultipleValues(path):
    values = []
    path_string = ""
    for i in range(0, len(path) - 1):
        path_string += path[i]
        if i != len(path) - 1:
            path_string += "/"
    elements = root.findall(path_string, namespaces)
    for element in elements:
        value = element.text
        values.append(value)
    return (values)


def getKeywordList(type):
    klist = []
    keywordTypes = root.findall(
        "gmd:identificationInfo/gmd:MD_DataIdentification/gmd:descriptiveKeywords/gmd:MD_Keywords/gmd:type/gmd:MD_KeywordTypeCode",
        namespaces)
    for keywordType in keywordTypes:
        if keywordType.text == type:
            parent = keywordType.getparent().getparent()

            keywordElements = parent.findall("gmd:keyword", namespaces)
            for keywordElement in keywordElements:

                value = keywordElement.getchildren()[0].text
                if value is not None:
                    for words in value.split(","):
                        klist.append(value)

    return (list(set(klist)))


def getOrganizationName(type):
    organizationTypes = root.findall(
        "gmd:identificationInfo/gmd:MD_DataIdentification/gmd:citation/gmd:CI_Citation/gmd:citedResponsibleParty/gmd:CI_ResponsibleParty/gmd:role/gmd:CI_RoleCode",
        namespaces)
    for orgType in organizationTypes:
        if orgType.text == type:
            parent = orgType.getparent().getparent()
            org_element = parent.find("gmd:organisationName", namespaces)  # /gco:CharacterString", namespaces)
            char_element = org_element.find("gco:CharacterString", namespaces)  #
            text = char_element.text
            return (text)


def mapIsoSubjects(list):
    for index, item in enumerate(list):
        if (item in isoTopicCategoriesMap):
            list[index] = isoTopicCategoriesMap[item]

    return (list)


def setOutDir(lyr_id, odir):
    """per OpenGeoMetadata standards, metadata files should be organized by either the geoblacklight
    layer_id_s name given in the layer_id_s value of geoblacklight. E.g. if the layer_id_s value is
    'UniversityLibrary:Arizona_AmerIndianReservations_1900', the fvn-1a (64 bit) hash would be
    calculated from 'Arizona_AmerIndianReservations_1900'.  The fvn-1a hash algorythm outputs a 10
    digit number, so the directory structure will be split into 3,3,2,2. E.g. if the hash is
    3285418445, the directory structure will be 328/541/84/45

    https: // github.com / OpenGeoMetadata / metadatarepository / issues / 3
    """
    sep = os.sep

    if not os.path.exists(odir):
        # print(dir)
        os.mkdir(odir)

    llegal_folder_names = ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7",
                           "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
    salt = ""
    hash = hash_dn(layerid, salt).replace("_", "").replace("-", "")
    for iffn in llegal_folder_names:
        while iffn.lower() in hash.lower():
            salt += " "
            hash = hash_dn(layerid, salt).replace("_", "").replace("-", "")

    dirlist = [hash[0:3], hash[3:6], hash[6:8], hash[8:10]]
    dirstring = hash[0:3] + sep + hash[3:6] + sep + hash[6:8] + sep + hash[8:10]

    for dir in dirlist:
        odir = os.path.join(odir,dir)
        if not os.path.exists(odir):
            # print(dir)
            os.mkdir(odir)

    return dirstring


def createDictionary(dict, file):
    dict["dc_identifier_s"] = getSingleValue(["gmd:dataSetURI",
                                              "gco:CharacterString"])

    dict["dc_title_s"] = getSingleValue(["gmd:identificationInfo",
                                         "gmd:MD_DataIdentification",
                                         "gmd:citation",
                                         "gmd:CI_Citation",
                                         "gmd:title",
                                         "gco:CharacterString"])

    dict["dc_description_s"] = getSingleValue(["gmd:identificationInfo",
                                               "gmd:MD_DataIdentification",
                                               "gmd:abstract",
                                               "gco:CharacterString"])

    # Point, Line, Polygon, or Raster
    dict["layer_geom_type_s"] = getDataType(file)[0]

    # Metadata Modifed date
    dict["layer_modified_dt"] = getSingleValue(["gmd:dateStamp",
                                                "gco:Date"]) + "Z"  # for solr date formatting
    # Data format
    dict["dc_format_s"] = getSingleValue(["gmd:distributionInfo",
                                          "gmd:MD_Distribution",
                                          "gmd:distributor",
                                          "gmd:MD_Distributor",
                                          "gmd:distributorFormat",
                                          "gmd:MD_Format",
                                          "gmd:name",
                                          "gco:CharacterString"])

    # Metadata Language
    dict["dc_language_s"] = getSingleValue(["gmd:language",
                                            "gmd:LanguageCode"])

    # "Dataset" or "Image" or "PhysicalObject"
    dict["dc_type_s"] = getDataType(file)[1]

    role = getSingleValue(["gmd:identificationInfo",
                           "gmd:MD_DataIdentification",
                           "gmd:citation",
                           "gmd:CI_Citation",
                           "gmd:citedResponsibleParty",
                           "gmd:CI_ResponsibleParty",
                           "gmd:role",
                           "gmd:CI_RoleCode"])

    # Publisher Name
    # if role = publisher
    dict["dc_publisher_s"] = getOrganizationName("publisher")
    dict["dc_creator_sm"] = getOrganizationName("originator")

    # Place Names.  May need to be geonames.
    dict["dct_spatial_sm"] = getKeywordList("place")
    # A list of all subject keywords including topic Categories (topicCategory)
    descritiveKeywords = getKeywordList("theme")

    topicCategories = mapIsoSubjects(getMultipleValues(["gmd:identificationInfo",
                                                        "gmd:MD_DataIdentification",
                                                        "gmd:topicCategory",
                                                        "gmd:MD_TopicCategoryCode"]))

    keywords = descritiveKeywords + topicCategories
    # LIST OF KEYWORDS
    dict["dc_subject_sm"] = keywords

    # Date issued, Issued date for the layer, using XML Schema dateTime format (YYYY-MM-DDThh:mm:ssZ). OPTIONAL
    dict["dct_issued_s"] = getSingleValue(["gmd:identificationInfo",
                                           "gmd:MD_DataIdentification",
                                           "gmd:citation",
                                           "gmd:CI_Citation",
                                           "gmd:date",
                                           "gmd:CI_Date",
                                           "gmd:date",
                                           "gco:Date"])

    # Date or range of dates of content (years only). If range, separated by hyphen
    try:
        begDate = getSingleValue(["gmd:identificationInfo",
                                  "gmd:MD_DataIdentification",
                                  "gmd:extent",
                                  "gmd:EX_Extent",
                                  "gmd:temporalElement",
                                  "gmd:EX_TemporalExtent",
                                  "gmd:extent",
                                  "gml:TimePeriod",
                                  "gml:beginPosition"])

        endDate = getSingleValue(["gmd:identificationInfo",
                                  "gmd:MD_DataIdentification",
                                  "gmd:extent",
                                  "gmd:EX_Extent",
                                  "gmd:temporalElement",
                                  "gmd:EX_TemporalExtent",
                                  "gmd:extent",
                                  "gml:TimePeriod",
                                  "gml:endPosition"])
    except:
        endDate = getSingleValue(["gmd:identificationInfo",
                                  "gmd:MD_DataIdentification",
                                  "gmd:extent",
                                  "gmd:EX_Extent",
                                  "gmd:temporalElement",
                                  "gmd:EX_SpatialTemporalExtent",
                                  "gmd:extent",
                                  "gml:TimeInstant",
                                  "gml:timePosition"])

    wbound = getSingleValue(["gmd:identificationInfo",
                             "gmd:MD_DataIdentification",
                             "gmd:extent",
                             "gmd:EX_Extent",
                             "gmd:geographicElement",
                             "gmd:EX_GeographicBoundingBox",
                             "gmd:westBoundLongitude",
                             "gco:Decimal"])

    ebound = getSingleValue(["gmd:identificationInfo",
                             "gmd:MD_DataIdentification",
                             "gmd:extent",
                             "gmd:EX_Extent",
                             "gmd:geographicElement",
                             "gmd:EX_GeographicBoundingBox",
                             "gmd:eastBoundLongitude",
                             "gco:Decimal"])

    nbound = getSingleValue(["gmd:identificationInfo",
                             "gmd:MD_DataIdentification",
                             "gmd:extent",
                             "gmd:EX_Extent",
                             "gmd:geographicElement",
                             "gmd:EX_GeographicBoundingBox",
                             "gmd:northBoundLatitude",
                             "gco:Decimal"])

    sbound = getSingleValue(["gmd:identificationInfo",
                             "gmd:MD_DataIdentification",
                             "gmd:extent",
                             "gmd:EX_Extent",
                             "gmd:geographicElement",
                             "gmd:EX_GeographicBoundingBox",
                             "gmd:southBoundLatitude",
                             "gco:Decimal"])

    # Bounding box as maximum values for S W N E.
    # dict["georss_box_s"] = sbound + " " + wbound + " " + nbound + " " + ebound
    # Shape of the layer as a ENVELOPE WKT using W E N S.
    dict["solr_geom"] = "ENVELOPE(" + wbound + ", " + ebound + ", " + nbound + ", " + sbound + ")"

    dict["solr_year_i"] = endDate[0:4]

    # Holding dataset for the layer, such as the name of a collection. OPTIONAL
    dict["dct_isPartOf_sm"] = []
    # CONSTANTS
    dict["dc_rights_s"] = rights
    dict["dct_provenance_s"] = institution
    dict["geoblacklight_version"] = gbl_schema_version
    # GeoserverWorkspace:LayerName.  University of Arizona Unique
    fileName_noext = file.split(".")[0]  # Removing path from file path
    dict["layer_id_s"] = layerid_prefix + ":" + fileName_noext

    # temporal (year only)
    if 'begDate' in locals():
        if begDate[:4] == endDate[:4]:
            date = endDate[0:4]
        else:
            date = begDate[0:4] + "-" + endDate[0:4]
    else:
        date = endDate

    dict["dct_temporal_sm"] = date

    dict["dct_references_s"] = OrderedDict()

    dict["dct_references_s"][
        "http://www.opengis.net/def/serviceType/ogc/wms"] = geoserver_loc + "/wms"
    if getDataType(file)[1] == "Dataset":
        dict["dct_references_s"]["http://www.opengis.net/def/serviceType/ogc/wfs"] = geoserver_loc + "/wfs"
    elif getDataType(file)[1] == "Image":
        dict["dct_references_s"]["http://www.opengis.net/def/serviceType/ogc/wcs"] = geoserver_loc + "/wcs"
    else:
        print("ERROR: Unknown Data Type. Exiting")
        exit()
    # Image viewer using Leaflet-IIIF "http://iiif.io/api/image":"",
    # Direct file download feature "http://schema.org/downloadUrl":"http://stacks.stanford.edu/file/druid:rf385pb1942/data.zip",
    # Data dictionary / documentation download "http://lccn.loc.gov/sh85035852":"",
    # Full layer description (mods link for Stanford) "http://schema.org/url":"http://purl.stanford.edu/rf385pb1942",
    # Metadata in ISO "\"http://www.isotc211.org/schemas/2005/gmd/\":"http://opengeometadata.stanford.edu/metadata/edu.stanford.purl/druid:rf385pb1942/iso19139.xml",
    # Metadata in MODS "http://www.loc.gov/mods/v3":"http://purl.stanford.edu/rf385pb1942.mods",
    # Metadata in HTML "http://www.w3.org/1999/xhtml":"http://opengeometadata.stanford.edu/metadata/edu.stanford.purl/druid:rf385pb1942/default.html",
    # ArcGIS FeatureLayer "urn:x-esri:serviceType:ArcGIS#FeatureLayer":"",
    # ArcGIS TiledMapLayer "urn:x-esri:serviceType:ArcGIS#TiledMapLayer":"",
    # ArcGIS DynamicMapLayer "urn:x-esri:serviceType:ArcGIS#DynamicMapLayer":"",
    # ArcGIS ImageMapLayer "urn:x-esri:serviceType:ArcGIS#ImageMapLayer",""

    """ A slug identifies a layer in, ideally, human-readable keywords. This value
    is visible to the user and used for Permalinks. The value should be
    alpha-numeric characters separated by dashes, and is typically of the form
    institution-keyword1-keyword2. It should also be globally unique across all
    institutions in your GeoBlacklight index. Some examples of slugs include:
        india-map
        stanford-andhra-pradesh-village-boundaries
        stanford-aa111bb2222 (valid, but not ideal as it's not human-readable) """
    dict["layer_slug_s"] = institution.lower() + getSlugWords(fileName_noext)

    return (dict)

args = parser.parse_args()
outdir = checkpath(args.outdir) if args.outdir else "./hashedDir"
metadatadir = checkpath(args.mddir) if args.mddir else "./"
datadir = checkpath(args.datadir) if args.datadir else "./"
rights = args.rights if args.rights else "Public"           # Public or Restricted
if rights.lower() != "public" and rights.lower() != "restricted":
    print("ERROR: Access rights value should be one of \"Public\" or \"Restricted\". Exiting.")
    exit()
institution = args.institution if args.institution else "UArizona"    # Name of holding institution
gbl_schema_version = args.version if args.version else "1.0"
layerid_prefix = args.workspace if args.workspace else "UniversityLibrary"    # Corresponds to Geoserver Workspace
isometadata_link = args.mdurl if args.mdurl else r"https://raw.githubusercontent.com/OpenGeoMetadata/edu." + institution.lower()   # Location of metadata files
tosolr = args.tosolr if args.tosolr else "False"
if tosolr != "True" and tosolr != "False":
    print("ERROR: tosolr variable should be either \"True\" or \"False\". Exiting.")
    exit()

print("Beginning execution with variables:"
      "\n  Metadata Directory:", metadatadir,
      "\n  Output Directory:", outdir,
      "\n  Data Directory:", datadir,
      "\n  Access Rights:", rights,
      "\n  Institution:", institution,
      "\n  Schema Version:", gbl_schema_version,
      "\n  LayerId Prefix:", layerid_prefix,
      "\n  Metadata Url Prefix:", isometadata_link,
      "\n  POST to Solr:", tosolr, "\n")

isoTopicCategoriesMap = {"farming":"Farming",
                         "biota":"Biota",
                         "boundaries":"Boundaries",
                         "climatologyAtmosphere":"Climatology/Meteorology/Atmosphere",
                         "economy":"Economy",
                         "elevation":"Elevation",
                         "environment":"Environment",
                         "geoscientificInformation":"Geoscientific Information",
                         "health":"Health",
                         "imageryBaseMapsEarthCover":"Imagery/Base Maps/Earth Cover",
                         "intelligenceMilitary":"Intelligence/Military",
                         "inlandWaters":"Inland Waters",
                         "location":"Location",
                         "oceans":"Oceans",
                         "planningCadastre":"Planning Cadastre",
                         "society":"Society",
                         "structure":"Structure",
                         "transportation":"Transportation",
                         "utilitiesCommunications":"Utilities/Communications"}

gmd = r"http://www.isotc211.org/2005/gmd"
gml = r"http://www.opengis.net/gml"
gco = r"http://www.isotc211.org/2005/gco"
gts = r"http://www.isotc211.org/2005/gts"

namespaces = {'gmd':gmd,
              'gml':gml,
              'gco':gco,
              'gts':gts}

ET.register_namespace("gmd", gmd)
ET.register_namespace("gml", gml)
ET.register_namespace("gco", gco)
ET.register_namespace("gts", gts)



# BUILD LIST OF DATA FILES TO MATCH FROM
filelist = {}
for dir_root, dirs, files in os.walk(datadir):
    dirs[:] = [d for d in dirs if d not in ["ARIA"]]
    for file in files:
        if file.endswith(".shp") or file.endswith(".tif"):
            fpath = os.path.join(dir_root, file)
            filelist[file] = fpath

print("\n...Finished building file list from data directory...")
# INDEX OF GEOBLACKLIGHT layer_id_s AND CALCULATED HASH. USED TO ALLOW REFERENCE OF ORIGINAL DATASET NAME TO
#  OPENGEOMETADATA DIRECTORY STRUCTURE.
layers_json = {}

print("\n...Beginning crawl of metadata directory...")
for dir_root, dirs, files in os.walk(metadatadir):
    for file in files:
        if file.endswith(".xml"):
            print("Starting", file)
            fpath = os.path.join(dir_root, file)
            tree = ET.parse(fpath)
            root = tree.getroot()
            gblschema = OrderedDict({
                                "layer_slug_s": "",
                                "dc_identifier_s": "",
                                "dc_title_s": "",
                                "dc_description_s": "",
                                "dc_rights_s": "",
                                "dct_provenance_s": "",
                                "dct_references_s": OrderedDict(),
                                "layer_id_s": "",
                                "dct_isPartOf_sm": [],
                                "layer_geom_type_s": "",
                                "layer_modified_dt": "",
                                "dc_format_s": "",
                                "dc_language_s": "",
                                "dc_type_s": "",
                                "dc_publisher_s": "",
                                "dc_creator_sm": "",
                                "dc_subject_sm": [],
                                "dct_issued_s": "",
                                "dct_temporal_sm": [],
                                "dct_spatial_sm": [],
                                "solr_geom": "",
                                "solr_year_i": "",
                                "geoblacklight_version": ""
                        })

            gblSchemaDict = createDictionary(gblschema,file)
            layerid = gblSchemaDict["layer_id_s"]
            #print("outdir parent", outdir)
            outpath = setOutDir(layerid, outdir)
            foutdir = outdir + "/" + outpath
            #print("outdir hash", foutdir)

            xml_location = isometadata_link + "/master/" + outpath.replace("\\","/") + "/" + "iso19139.xml"

            # add xml location to dct_references_s value
            gblSchemaDict["dct_references_s"]["http://www.isotc211.org/schemas/2005/gmd/"] = xml_location
            # dct_references_s needs to be a string value
            refs = json.dumps(gblSchemaDict["dct_references_s"])
            gblSchemaDict["dct_references_s"] = refs

            # SET COLLECTIONS BASED ON FOLDER STRUCTURE OF ORIGINAL
            collections = os.path.relpath(fpath, metadatadir).split(os.sep)[:-1]
            gblSchemaDict["dct_isPartOf_sm"] = collections

            jsonString = json.dumps(gblSchemaDict, indent=4, sort_keys=False)

            # SET OUTPUT FILE VALUES
            outfile_json = foutdir + "/" + "geoblacklight.json"
            outfile_isoxml = foutdir + "/" + "iso19139.xml"

            # UPLOAD RECORD TO SOLR INDEX
            if tosolr.lower() == "true":
                solrDict = {"add": {"doc": gblSchemaDict}}
                solrString = json.dumps(solrDict, indent=4, sort_keys=False)
                headers = {"content-type": "application/json"}
                r = requests.post(solrURL, data=solrString, headers= headers)

            # write geoblacking schema values to json file
            with open(outfile_json, 'w') as jfile:
                jfile.write(jsonString)

            shutil.copy(fpath, outfile_isoxml)

            # add to layers_json dictionary
            layers_json[layerid] = outpath

# WRITE the layers.json with a line noting the file name and the hash association
ljsondile = outdir + "/layers.json"
with open(ljsondile, 'w+') as lfile:
    jstring = json.dumps(layers_json, indent=4, sort_keys=False)
    lfile.write(jstring)

print("FINISHED")
